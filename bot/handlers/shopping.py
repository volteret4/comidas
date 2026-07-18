from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .. import planner
from ..db import get_connection
from .planning import today_local


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_connection()
    today = today_local()
    week_start = today - timedelta(days=today.weekday())
    plan = planner.get_weekly_plan_by_week_start(conn, week_start)
    if plan is None:
        await update.message.reply_text("Todavía no hay ningún plan para esta semana. Usa /planificar.")
        return
    await update.message.reply_text(planner.shopping_list_text(conn, plan))


async def semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /semana AAAA-MM-DD (cualquier fecha de esa semana)")
        return
    try:
        given = date.fromisoformat(context.args[0])
    except ValueError:
        await update.message.reply_text("Formato de fecha no válido, usa AAAA-MM-DD.")
        return

    week_start = given - timedelta(days=given.weekday())
    conn = get_connection()
    plan = planner.get_weekly_plan_by_week_start(conn, week_start)
    if plan is None:
        await update.message.reply_text(f"No hay ningún plan para la semana del {week_start.strftime('%d/%m')}.")
        return
    await update.message.reply_text(planner.week_summary_text(conn, plan))
    await update.message.reply_text(planner.shopping_list_text(conn, plan))


def register(application: Application) -> None:
    application.add_handler(CommandHandler("lista", lista))
    application.add_handler(CommandHandler("semana", semana))
