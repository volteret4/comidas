from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import caldav

from .config import config

logger = logging.getLogger(__name__)

RECOGNIZED_SHIFTS = {"MT", "M", "T"}


def fetch_shifts(start: date, end: date) -> dict[date, str]:
    """Lee el calendario Turnos en Radicale para el rango [start, end] (ambos incluidos).

    Devuelve {fecha: 'MT'|'M'|'T'} solo para los días trabajados; los días sin
    evento se consideran libres y no aparecen en el resultado. Un summary no
    reconocido se loguea como warning y se trata como día libre (falla seguro
    en vez de tumbar la planificación entera por un evento suelto mal escrito).
    """
    client = caldav.DAVClient(
        url=config.radicale_url,
        username=config.radicale_username,
        password=config.radicale_password,
    )
    principal = client.principal()
    calendar = principal.calendar(name=config.radicale_calendar_name)

    # el rango de date_search es exclusivo en el extremo final para búsquedas de día completo
    events = calendar.date_search(start=start, end=end + timedelta(days=1))

    shifts: dict[date, str] = {}
    for event in events:
        component = event.icalendar_component
        summary = str(component.get("summary", "")).strip().upper()
        dtstart = component.get("dtstart").dt
        event_date = dtstart.date() if isinstance(dtstart, datetime) else dtstart

        if summary not in RECOGNIZED_SHIFTS:
            logger.warning("Turno no reconocido %r el %s en el calendario Turnos, se trata como día libre", summary, event_date)
            continue
        shifts[event_date] = summary

    return shifts
