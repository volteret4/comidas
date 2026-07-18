from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from .config import config
from .db import get_connection
from .handlers import register_handlers
from .handlers.planning import schedule_weekly_job
from .seed_dishes import seed_if_empty

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hola, soy tu bot de comidas. Usa /addplato o /addplatourl para dar de alta platos, "
        "/listaplatos para ver el catálogo, y /planificar cuando quieras organizar la semana."
    )


def main() -> None:
    conn = get_connection()
    seeded = seed_if_empty(conn)
    if seeded:
        logger.info("Catálogo vacío: se han añadido %d platos de ejemplo", seeded)

    application = ApplicationBuilder().token(config.telegram_bot_token).build()

    # el gatekeeper de auth se registra primero (group=-1) desde dentro de su propio módulo
    from . import auth

    auth.register(application)

    application.add_handler(CommandHandler("start", start))
    register_handlers(application)
    schedule_weekly_job(application)

    logger.info(
        "Bot arrancado. Job semanal: %s %s (%s)",
        config.weekly_job_day, config.weekly_job_time, config.tz,
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
