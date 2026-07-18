from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

from . import caldav_client
from .models import Dish, Leftover, PlanSlot, WeeklyPlan
from .shift_rules import slot_constraint

MEAL_ORDER = ("comida", "cena")


def get_target_week_start(conn: sqlite3.Connection, today: date) -> date:
    candidate = today - timedelta(days=today.weekday())
    row = conn.execute(
        "SELECT status FROM weekly_plans WHERE week_start_date=?", (candidate.isoformat(),)
    ).fetchone()
    if row and row["status"] == "complete":
        candidate += timedelta(days=7)
    return candidate


def get_or_create_weekly_plan(conn: sqlite3.Connection, week_start: date, today: date) -> WeeklyPlan:
    """Crea el plan y sus plan_slots si no existían todavía. Si la semana ya ha empezado
    (p.ej. un /planificar ad-hoc a mitad de semana sin plan previo), solo se crean slots
    desde hoy en adelante — los días ya pasados no se preguntan ni cuentan para completar el plan."""
    row = conn.execute(
        "SELECT * FROM weekly_plans WHERE week_start_date=?", (week_start.isoformat(),)
    ).fetchone()
    if row:
        return WeeklyPlan.from_row(row)

    week_end = week_start + timedelta(days=6)
    shifts = caldav_client.fetch_shifts(week_start, week_end)
    _cache_shifts(conn, shifts)

    cur = conn.execute("INSERT INTO weekly_plans (week_start_date) VALUES (?)", (week_start.isoformat(),))
    plan_id = cur.lastrowid

    start_day = max(week_start, today)
    day = start_day
    while day <= week_end:
        shift_type = shifts.get(day)
        for meal_type in MEAL_ORDER:
            conn.execute(
                "INSERT INTO plan_slots (weekly_plan_id, slot_date, meal_type, shift_type) VALUES (?, ?, ?, ?)",
                (plan_id, day.isoformat(), meal_type, shift_type),
            )
        day += timedelta(days=1)
    conn.commit()
    return WeeklyPlan(id=plan_id, week_start_date=week_start.isoformat(), status="in_progress")


def _cache_shifts(conn: sqlite3.Connection, shifts: dict[date, str]) -> None:
    for day, shift_type in shifts.items():
        conn.execute(
            "INSERT INTO shift_cache (slot_date, shift_type) VALUES (?, ?) "
            "ON CONFLICT(slot_date) DO UPDATE SET shift_type=excluded.shift_type, fetched_at=CURRENT_TIMESTAMP",
            (day.isoformat(), shift_type),
        )
    conn.commit()


def apply_leftovers(conn: sqlite3.Connection, plan: WeeklyPlan) -> list[str]:
    """Asigna a esta semana los sobrantes de lote pendientes de semanas anteriores.

    Devuelve mensajes informativos (uno por sobrante que consiguió asignar al menos
    un día) para avisar al usuario antes de empezar a preguntar nada nuevo.
    """
    messages: list[str] = []
    leftover_rows = conn.execute(
        "SELECT * FROM batch_leftovers WHERE consumed = 0 ORDER BY created_at ASC"
    ).fetchall()

    for lo_row in leftover_rows:
        leftover = Leftover.from_row(lo_row)
        dish_row = conn.execute("SELECT * FROM dishes WHERE id=?", (leftover.dish_id,)).fetchone()
        if dish_row is None:
            conn.execute("UPDATE batch_leftovers SET consumed=1 WHERE id=?", (leftover.id,))
            continue
        dish = Dish.from_row(dish_row)

        slot_rows = conn.execute(
            "SELECT * FROM plan_slots WHERE weekly_plan_id=? AND meal_type=? AND dish_id IS NULL "
            "ORDER BY slot_date ASC",
            (plan.id, leftover.meal_type),
        ).fetchall()

        assigned = 0
        anchor_id: int | None = None
        for slot_row in slot_rows:
            if assigned >= leftover.remaining_days:
                break
            slot = PlanSlot.from_row(slot_row)
            constraint = slot_constraint(slot.shift_type, slot.meal_type)
            if constraint is not None and not dish.has_tag(constraint):
                continue
            if anchor_id is None:
                anchor_id = slot.id
            conn.execute(
                "UPDATE plan_slots SET dish_id=?, batch_group_id=?, from_leftover=1, "
                "resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                (dish.id, anchor_id, slot.id),
            )
            assigned += 1

        if assigned > 0:
            messages.append(
                f'Ya tienes {assigned} {leftover.meal_type}(s) de "{dish.name}" que sobraron de antes.'
            )

        remaining = leftover.remaining_days - assigned
        if remaining <= 0:
            conn.execute("UPDATE batch_leftovers SET consumed=1 WHERE id=?", (leftover.id,))
        else:
            conn.execute("UPDATE batch_leftovers SET remaining_days=? WHERE id=?", (remaining, leftover.id))

    conn.commit()
    return messages


def next_unresolved_slot(conn: sqlite3.Connection, weekly_plan_id: int) -> PlanSlot | None:
    """Siguiente slot sin resolver de este plan, sin importar cuánto tiempo lleve pendiente
    (si el usuario tarda días en contestar un botón, ese slot sigue siendo el primero a resolver)."""
    row = conn.execute(
        "SELECT * FROM plan_slots WHERE weekly_plan_id=? AND dish_id IS NULL "
        "ORDER BY slot_date ASC, CASE meal_type WHEN 'comida' THEN 0 ELSE 1 END ASC LIMIT 1",
        (weekly_plan_id,),
    ).fetchone()
    return PlanSlot.from_row(row) if row else None


def candidate_dishes(conn: sqlite3.Connection, slot: PlanSlot, weekly_plan_id: int, limit: int = 3) -> list[Dish]:
    constraint = slot_constraint(slot.shift_type, slot.meal_type)
    meal_col = "for_comida" if slot.meal_type == "comida" else "for_cena"

    used_ids = {
        row["dish_id"]
        for row in conn.execute(
            "SELECT DISTINCT dish_id FROM plan_slots WHERE weekly_plan_id=? AND dish_id IS NOT NULL",
            (weekly_plan_id,),
        ).fetchall()
    }

    query = f"SELECT * FROM dishes WHERE active=1 AND {meal_col}=1"
    if constraint is not None:
        query += f" AND {constraint}=1"
    dishes = [Dish.from_row(r) for r in conn.execute(query).fetchall()]

    fresh_pool = [d for d in dishes if d.id not in used_ids]
    if len(fresh_pool) >= limit:
        pool = fresh_pool
    else:
        used_pool = [d for d in dishes if d.id in used_ids]
        random.shuffle(used_pool)
        pool = fresh_pool + used_pool[: limit - len(fresh_pool)]

    random.shuffle(pool)
    return pool[:limit]


def resolve_slot_direct(conn: sqlite3.Connection, slot: PlanSlot, dish: Dish) -> None:
    """Asigna un plato a un único slot (usado para platos frescos, o lotes sin más días compatibles)."""
    conn.execute(
        "UPDATE plan_slots SET dish_id=?, batch_group_id=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
        (dish.id, slot.id, slot.id),
    )
    conn.commit()


def compute_batch_candidates(conn: sqlite3.Connection, weekly_plan_id: int, anchor_slot: PlanSlot, dish: Dish) -> list[PlanSlot]:
    """Slots de esta semana, posteriores al ancla, del mismo tipo de comida, sin resolver y
    compatibles con las etiquetas del plato — hasta el límite que da su rendimiento."""
    cap = dish.rendimiento - 1
    if cap <= 0:
        return []

    rows = conn.execute(
        "SELECT * FROM plan_slots WHERE weekly_plan_id=? AND meal_type=? AND slot_date > ? AND dish_id IS NULL "
        "ORDER BY slot_date ASC",
        (weekly_plan_id, anchor_slot.meal_type, anchor_slot.slot_date),
    ).fetchall()

    eligible: list[PlanSlot] = []
    for row in rows:
        if len(eligible) >= cap:
            break
        slot = PlanSlot.from_row(row)
        constraint = slot_constraint(slot.shift_type, slot.meal_type)
        if constraint is not None and not dish.has_tag(constraint):
            continue
        eligible.append(slot)
    return eligible


def assign_batch(conn: sqlite3.Connection, anchor_slot: PlanSlot, dish: Dish, eligible_slots: list[PlanSlot], n: int) -> None:
    """Asigna el ancla + los primeros n slots elegibles a este plato, y guarda como sobrante
    (para la semana siguiente) la capacidad del lote que no se ha usado esta semana."""
    chosen = eligible_slots[:n]
    conn.execute(
        "UPDATE plan_slots SET dish_id=?, batch_group_id=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
        (dish.id, anchor_slot.id, anchor_slot.id),
    )
    for slot in chosen:
        conn.execute(
            "UPDATE plan_slots SET dish_id=?, batch_group_id=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
            (dish.id, anchor_slot.id, slot.id),
        )

    leftover_days = (dish.rendimiento - 1) - n
    if leftover_days > 0:
        conn.execute(
            "INSERT INTO batch_leftovers (dish_id, meal_type, remaining_days, source_weekly_plan_id) "
            "VALUES (?, ?, ?, ?)",
            (dish.id, anchor_slot.meal_type, leftover_days, anchor_slot.weekly_plan_id),
        )
    conn.commit()


def is_plan_complete(conn: sqlite3.Connection, weekly_plan_id: int) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM plan_slots WHERE weekly_plan_id=? AND dish_id IS NULL", (weekly_plan_id,)
    ).fetchone()
    return row["c"] == 0


def mark_complete(conn: sqlite3.Connection, weekly_plan_id: int) -> None:
    conn.execute("UPDATE weekly_plans SET status='complete' WHERE id=?", (weekly_plan_id,))
    conn.commit()


def shopping_list_text(conn: sqlite3.Connection, plan: WeeklyPlan) -> str:
    rows = conn.execute(
        "SELECT DISTINCT batch_group_id, dish_id FROM plan_slots "
        "WHERE weekly_plan_id=? AND dish_id IS NOT NULL AND from_leftover=0",
        (plan.id,),
    ).fetchall()

    if not rows:
        return "No hay ningún plato asignado todavía esta semana."

    lines = [f"🛒 Lista de la compra — semana del {_format_date(plan.week_start_date)}", ""]
    for row in rows:
        dish_row = conn.execute("SELECT * FROM dishes WHERE id=?", (row["dish_id"],)).fetchone()
        dish = Dish.from_row(dish_row)
        coverage_rows = conn.execute(
            "SELECT meal_type, COUNT(*) AS c FROM plan_slots WHERE batch_group_id=? GROUP BY meal_type",
            (row["batch_group_id"],),
        ).fetchall()
        coverage_desc = ", ".join(f"{c['c']} {c['meal_type']}(s)" for c in coverage_rows)
        lines.append(f"{dish.name} (cubre {coverage_desc}):")
        for ingredient in dish.ingredients:
            lines.append(f"  - {ingredient}")
        lines.append("")

    return "\n".join(lines).strip()


def week_summary_text(conn: sqlite3.Connection, plan: WeeklyPlan) -> str:
    rows = conn.execute(
        "SELECT * FROM plan_slots WHERE weekly_plan_id=? ORDER BY slot_date ASC, "
        "CASE meal_type WHEN 'comida' THEN 0 ELSE 1 END ASC",
        (plan.id,),
    ).fetchall()

    lines = [f"📅 Semana del {_format_date(plan.week_start_date)}", ""]
    current_date = None
    for row in rows:
        if row["slot_date"] != current_date:
            current_date = row["slot_date"]
            lines.append(f"— {_format_date(current_date)} ({row['shift_type'] or 'libre'}) —")
        dish_name = "(sin asignar)"
        if row["dish_id"] is not None:
            dish_row = conn.execute("SELECT name FROM dishes WHERE id=?", (row["dish_id"],)).fetchone()
            dish_name = dish_row["name"] if dish_row else "(sin asignar)"
        lines.append(f"  {row['meal_type'].capitalize()}: {dish_name}")
    return "\n".join(lines)


def get_weekly_plan_by_week_start(conn: sqlite3.Connection, week_start: date) -> WeeklyPlan | None:
    row = conn.execute(
        "SELECT * FROM weekly_plans WHERE week_start_date=?", (week_start.isoformat(),)
    ).fetchone()
    return WeeklyPlan.from_row(row) if row else None


def _format_date(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%d/%m")
