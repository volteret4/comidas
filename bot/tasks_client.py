from __future__ import annotations

import logging
from datetime import date

import caldav

from .config import config

logger = logging.getLogger(__name__)


def push_shopping_list_task(week_start: date, shopping_text: str) -> None:
    """Crea (o actualiza si ya existe) en el calendario de tareas una tarea con la lista
    de la compra de esta semana, para no duplicarla si se llama varias veces."""
    client = caldav.DAVClient(
        url=config.radicale_url,
        username=config.radicale_username,
        password=config.radicale_password,
    )
    principal = client.principal()
    calendar = principal.calendar(name=config.radicale_tasks_calendar_name)

    summary = f"Compra semana del {week_start.strftime('%d/%m')}"

    try:
        for todo in calendar.search(todo=True):
            if str(todo.icalendar_component.get("summary", "")) == summary:
                with todo.edit_icalendar_component() as ical:
                    ical["description"] = shopping_text
                todo.save()
                return
    except Exception:
        logger.warning(
            "No se pudieron buscar tareas existentes en %s, se creará una nueva",
            config.radicale_tasks_calendar_name,
            exc_info=True,
        )

    calendar.add_todo(summary=summary, description=shopping_text, due=week_start)
