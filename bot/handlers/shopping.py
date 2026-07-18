from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .. import planner
from ..db import get_connection
from .planning import push_task_and_notify, today_local


def _current_week_start() -> date:
    today = today_local()
    return today - timedelta(days=today.weekday())


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_connection()
    plan = planner.get_weekly_plan_by_week_start(conn, _current_week_start())
    if plan is None:
        await update.message.reply_text("Todavía no hay ningún plan para esta semana. Usa /planificar.")
        return
    await update.message.reply_text(planner.shopping_list_text(conn, plan))


async def estasemana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_connection()
    plan = planner.get_weekly_plan_by_week_start(conn, _current_week_start())
    if plan is None:
        await update.message.reply_text("Todavía no hay ningún plan para esta semana. Usa /planificar.")
        return
    await update.message.reply_text(planner.week_summary_text(conn, plan))


async def tarea(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_connection()
    plan = planner.get_weekly_plan_by_week_start(conn, _current_week_start())
    if plan is None:
        await update.message.reply_text("Todavía no hay ningún plan para esta semana. Usa /planificar.")
        return
    shopping_text = planner.shopping_list_text(conn, plan)
    await push_task_and_notify(context, update.effective_chat.id, plan, shopping_text)


async def semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /semana AAAA-MM-DD (cualquier fecha de esa semana)")
        return
    try:
        given = date.fromisoformat(context.args[0])
    except ValueError:
        await update.message.reply_text("Formato de fecha no válido, usa AAAA-MM-DD.")
        return

    week_start_given = given - timedelta(days=given.weekday())
    conn = get_connection()
    plan = planner.get_weekly_plan_by_week_start(conn, week_start_given)
    if plan is None:
        await update.message.reply_text(f"No hay ningún plan para la semana del {week_start_given.strftime('%d/%m')}.")
        return
    await update.message.reply_text(planner.week_summary_text(conn, plan))
    await update.message.reply_text(planner.shopping_list_text(conn, plan))


def register(application: Application) -> None:
    application.add_handler(CommandHandler("lista", lista))
    application.add_handler(CommandHandler("estasemana", estasemana))
    application.add_handler(CommandHandler("tarea", tarea))
    application.add_handler(CommandHandler("semana", semana))
