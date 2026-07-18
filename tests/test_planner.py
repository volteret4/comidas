import json
from datetime import date, timedelta

import pytest

from bot import db as db_module
from bot import planner


def _monday_on_or_after(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7 or 7) if d.weekday() != 0 else d


@pytest.fixture
def conn():
    connection = db_module.connect(":memory:")
    yield connection
    connection.close()


def _insert_dish(conn, **kwargs) -> int:
    defaults = dict(
        for_comida=0, for_cena=0, fresco=0, tupper=0, rapido=0, rendimiento=1,
        ingredients=["ingrediente de prueba"], steps=[], metodo=None, source_url=None,
    )
    defaults.update(kwargs)
    cur = conn.execute(
        """INSERT INTO dishes (name, for_comida, for_cena, fresco, tupper, rapido, rendimiento,
           ingredients_json, steps_json, metodo, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["name"], defaults["for_comida"], defaults["for_cena"], defaults["fresco"],
            defaults["tupper"], defaults["rapido"], defaults["rendimiento"],
            json.dumps(defaults["ingredients"]), json.dumps(defaults["steps"]), defaults["metodo"],
            defaults["source_url"],
        ),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture(autouse=True)
def fake_shifts(monkeypatch):
    week_a_shifts = {}
    week_b_shifts = {}
    state = {"a_start": None, "b_start": None}

    def fetch_shifts(start, end):
        if state["a_start"] and start == state["a_start"]:
            return week_a_shifts
        if state["b_start"] and start == state["b_start"]:
            return week_b_shifts
        return {}

    monkeypatch.setattr("bot.planner.caldav_client.fetch_shifts", fetch_shifts)
    return week_a_shifts, week_b_shifts, state


def test_batch_assignment_creates_leftover_and_shopping_list_groups_by_batch(conn, fake_shifts):
    week_a_shifts, week_b_shifts, state = fake_shifts
    week_start = _monday_on_or_after(date(2026, 7, 20))
    state["a_start"] = week_start
    week_a_shifts[week_start] = "MT"
    week_a_shifts[week_start + timedelta(days=1)] = "MT"

    plan = planner.get_or_create_weekly_plan(conn, week_start, week_start)
    assert planner.apply_leftovers(conn, plan) == []

    batch_dish_id = _insert_dish(
        conn, name="Lentejas", for_comida=1, tupper=1, rendimiento=5,
        ingredients=["lentejas", "cebolla"],
    )

    monday_comida = planner.next_unresolved_slot(conn, plan.id)
    assert monday_comida.slot_date == week_start.isoformat()
    assert monday_comida.meal_type == "comida"

    batch_dish = _fetch_dish(conn, batch_dish_id)
    eligible = planner.compute_batch_candidates(conn, plan.id, monday_comida, batch_dish)
    # rendimiento=5 -> cap=4; hay 6 días de comida restantes tras el lunes, todos compatibles
    assert len(eligible) == 4

    planner.assign_batch(conn, monday_comida, batch_dish, eligible, n=2)

    covered = conn.execute(
        "SELECT COUNT(*) AS c FROM plan_slots WHERE batch_group_id=? AND dish_id=?",
        (monday_comida.id, batch_dish_id),
    ).fetchone()["c"]
    assert covered == 3  # ancla + 2

    leftover = conn.execute("SELECT * FROM batch_leftovers WHERE dish_id=?", (batch_dish_id,)).fetchone()
    assert leftover is not None
    assert leftover["remaining_days"] == 2
    assert leftover["consumed"] == 0

    # resolver el resto de slots con un plato fresco válido en cualquier franja
    fresh_dish_id = _insert_dish(
        conn, name="Salmón fresco", for_comida=1, for_cena=1, fresco=1, tupper=0, rapido=1, rendimiento=1,
        ingredients=["salmón"],
    )
    slot = planner.next_unresolved_slot(conn, plan.id)
    while slot is not None:
        dish = _fetch_dish(conn, fresh_dish_id)
        constraint = planner.slot_constraint(slot.shift_type, slot.meal_type)
        if constraint is None or dish.has_tag(constraint):
            planner.resolve_slot_direct(conn, slot, dish)
        else:
            # el turno MT-cena exige rapido, que el salmón cumple; MT-comida exige tupper, no lo cumple
            # -> usamos el propio plato de lote como comodín ahí también
            planner.resolve_slot_direct(conn, slot, batch_dish)
        slot = planner.next_unresolved_slot(conn, plan.id)

    assert planner.is_plan_complete(conn, plan.id)
    shopping = planner.shopping_list_text(conn, plan)
    assert "Lentejas" in shopping
    assert "cubre 3 comida(s)" in shopping or "3 comida" in shopping

    # -- semana siguiente: el sobrante de 2 días de Lentejas se debe aplicar automáticamente --
    week_b_start = week_start + timedelta(days=7)
    state["b_start"] = week_b_start
    plan_b = planner.get_or_create_weekly_plan(conn, week_b_start, week_b_start)
    messages = planner.apply_leftovers(conn, plan_b)
    assert len(messages) == 1
    assert "Lentejas" in messages[0]

    leftover_after = conn.execute("SELECT * FROM batch_leftovers WHERE dish_id=?", (batch_dish_id,)).fetchone()
    assert leftover_after["consumed"] == 1

    leftover_slots = conn.execute(
        "SELECT COUNT(*) AS c FROM plan_slots WHERE weekly_plan_id=? AND dish_id=? AND from_leftover=1",
        (plan_b.id, batch_dish_id),
    ).fetchone()["c"]
    assert leftover_slots == 2

    shopping_b = planner.shopping_list_text(conn, plan_b)
    assert "Lentejas" not in shopping_b  # ya se compró la semana anterior, no se repite


def _fetch_dish(conn, dish_id):
    from bot.models import Dish

    row = conn.execute("SELECT * FROM dishes WHERE id=?", (dish_id,)).fetchone()
    return Dish.from_row(row)
