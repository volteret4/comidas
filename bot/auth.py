from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes, TypeHandler

from .config import config

logger = logging.getLogger(__name__)


async def _reject_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    if chat.id != config.telegram_chat_id:
        logger.warning("Mensaje ignorado de chat_id no autorizado: %s", chat.id)
        raise ApplicationHandlerStop


def register(application: Application) -> None:
    application.add_handler(TypeHandler(Update, _reject_unauthorized), group=-1)
