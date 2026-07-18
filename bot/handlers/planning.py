from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from .. import planner, tasks_client
from ..config import config
from ..db import get_connection
from ..models import Dish, PlanSlot
from ..shift_rules import slot_constraint

logger = logging.getLogger(__name__)

# Desde PTB 20.0 el parámetro `days` de run_daily va de 0=domingo a 6=sábado.
_DAY_MAP = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}


def today_local() -> date:
    return datetime.now(ZoneInfo(config.tz)).date()


def _format_date(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%d/%m")


async def planificar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await advance(context, update.effective_chat.id)


async def weekly_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await advance(context, config.telegram_chat_id)


async def advance(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    conn = get_connection()
    today = today_local()
    week_start = planner.get_target_week_start(conn, today)
    is_new = planner.get_weekly_plan_by_week_start(conn, week_start) is None

    try:
        plan = planner.get_or_create_weekly_plan(conn, week_start, today)
    except Exception as exc:
        logger.exception("Fallo al leer el calendario Turnos")
        await context.bot.send_message(chat_id, f"No he podido leer el calendario de turnos: {exc}")
        return

    if is_new:
        for msg in planner.apply_leftovers(conn, plan):
            await context.bot.send_message(chat_id, msg)

    slot = planner.next_unresolved_slot(conn, plan.id)
    if slot is None:
        await _finalize(context, chat_id, plan)
        return

    await _prompt_slot(context, chat_id, plan, slot)


async def _prompt_slot(context: ContextTypes.DEFAULT_TYPE, chat_id: int, plan, slot: PlanSlot) -> None:
    conn = get_connection()
    candidates = planner.candidate_dishes(conn, slot, plan.id, limit=3)
    if not candidates:
        constraint = slot_constraint(slot.shift_type, slot.meal_type)
        needed = f" con la etiqueta {constraint}" if constraint else ""
        await context.bot.send_message(
            chat_id,
            f"No tengo ningún plato de {slot.meal_type}{needed} para el {_format_date(slot.slot_date)} "
            f"(turno {slot.shift_type or 'libre'}). Da de alta alguno con /addplato o /addplatourl y repite /planificar.",
        )
        return

    constraint = slot_constraint(slot.shift_type, slot.meal_type)
    constraint_txt = f" (necesita {constraint})" if constraint else ""
    header = (
        f"{_format_date(slot.slot_date)} — {slot.meal_type.capitalize()} — "
        f"Turno: {slot.shift_type or 'libre'}{constraint_txt}"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"🍽 {d.name}", callback_data=f"pick:{slot.id}:{d.id}")] for d in candidates]
    )
    await context.bot.send_message(chat_id, header, reply_markup=keyboard)


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, slot_id_s, dish_id_s = query.data.split(":")
    slot_id, dish_id = int(slot_id_s), int(dish_id_s)

    conn = get_connection()
    slot_row = conn.execute("SELECT * FROM plan_slots WHERE id=?", (slot_id,)).fetchone()
    dish_row = conn.execute("SELECT * FROM dishes WHERE id=?", (dish_id,)).fetchone()
    if slot_row is None or dish_row is None or slot_row["dish_id"] is not None:
        await query.edit_message_text("Esa franja ya no está disponible.")
        return
    slot = PlanSlot.from_row(slot_row)
    dish = Dish.from_row(dish_row)

    await query.edit_message_text(f"{query.message.text}\n\n➡️ {dish.name}")

    if dish.fresco:
        planner.resolve_slot_direct(conn, slot, dish)
        await advance(context, query.message.chat_id)
        return

    eligible = planner.compute_batch_candidates(conn, slot.weekly_plan_id, slot, dish)
    if not eligible:
        planner.resolve_slot_direct(conn, slot, dish)
        await advance(context, query.message.chat_id)
        return

    max_offer = len(eligible)
    buttons = [InlineKeyboardButton("Solo hoy", callback_data=f"batch:{slot.id}:{dish.id}:0")]
    buttons += [
        InlineKeyboardButton(f"+{n}", callback_data=f"batch:{slot.id}:{dish.id}:{n}")
        for n in range(1, max_offer + 1)
    ]
    rows = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    await context.bot.send_message(
        query.message.chat_id,
        f'¿Para cuántos días más de {slot.meal_type} repites "{dish.name}"? (hasta {max_offer} más)',
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def on_batch_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, slot_id_s, dish_id_s, n_s = query.data.split(":")
    slot_id, dish_id, n = int(slot_id_s), int(dish_id_s), int(n_s)

    conn = get_connection()
    slot_row = conn.execute("SELECT * FROM plan_slots WHERE id=?", (slot_id,)).fetchone()
    dish_row = conn.execute("SELECT * FROM dishes WHERE id=?", (dish_id,)).fetchone()
    if slot_row is None or dish_row is None or slot_row["dish_id"] is not None:
        await query.edit_message_text("Esa franja ya no está disponible.")
        return
    slot = PlanSlot.from_row(slot_row)
    dish = Dish.from_row(dish_row)

    eligible = planner.compute_batch_candidates(conn, slot.weekly_plan_id, slot, dish)
    planner.assign_batch(conn, slot, dish, eligible, n)

    await query.edit_message_text(f'{query.message.text}\n\n✅ {n} día(s) más asignados a "{dish.name}"')
    await advance(context, query.message.chat_id)


async def _finalize(context: ContextTypes.DEFAULT_TYPE, chat_id: int, plan) -> None:
    conn = get_connection()
    if not planner.is_plan_complete(conn, plan.id):
        return
    planner.mark_complete(conn, plan.id)
    await context.bot.send_message(chat_id, planner.week_summary_text(conn, plan))
    shopping_text = planner.shopping_list_text(conn, plan)
    await context.bot.send_message(chat_id, shopping_text)
    await push_task_and_notify(context, chat_id, plan, shopping_text)


async def push_task_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: int, plan, shopping_text: str) -> None:
    week_start = date.fromisoformat(plan.week_start_date)
    try:
        tasks_client.push_shopping_list_task(week_start, shopping_text)
    except Exception:
        logger.exception("Fallo al añadir la tarea al calendario %s", config.radicale_tasks_calendar_name)
        await context.bot.send_message(
            chat_id,
            f"⚠️ No he podido añadir la tarea al calendario \"{config.radicale_tasks_calendar_name}\".",
        )
        return
    await context.bot.send_message(chat_id, f'📋 Tarea añadida a tu calendario "{config.radicale_tasks_calendar_name}".')


def register(application: Application) -> None:
    application.add_handler(CommandHandler("planificar", planificar_command))
    application.add_handler(CallbackQueryHandler(on_pick, pattern="^pick:"))
    application.add_handler(CallbackQueryHandler(on_batch_count, pattern="^batch:"))


def schedule_weekly_job(application: Application) -> None:
    hour, minute = (int(x) for x in config.weekly_job_time.split(":"))
    day_code = _DAY_MAP[config.weekly_job_day.upper()]
    application.job_queue.run_daily(
        weekly_job,
        time=dt_time(hour=hour, minute=minute, tzinfo=ZoneInfo(config.tz)),
        days=(day_code,),
        name="weekly_planning",
    )
