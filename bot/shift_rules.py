from __future__ import annotations

MEAL_TYPES = ("comida", "cena")
SHIFT_TYPES = ("MT", "M", "T")


def slot_constraint(shift_type: str | None, meal_type: str) -> str | None:
    """Etiqueta de plato requerida ('tupper'|'rapido') para una franja, o None si no hay restricción.

    MT (7-22, doblete): comida ha de ser tupper (para llevar), cena rápida (llega ~22:00).
    M  (7-15, mañana):  comida rápida (come al llegar ~15:00), cena sin restricción.
    T  (15-22, tarde):  comida rápida (come antes de salir), cena rápida (llega tarde ~22:00).
    Día libre (sin evento, shift_type=None): sin restricción en ninguna comida.
    """
    if meal_type not in MEAL_TYPES:
        raise ValueError(f"meal_type desconocido: {meal_type!r}")
    if shift_type is None:
        return None
    if shift_type == "MT":
        return "tupper" if meal_type == "comida" else "rapido"
    if shift_type == "M":
        return "rapido" if meal_type == "comida" else None
    if shift_type == "T":
        return "rapido"
    raise ValueError(f"turno desconocido: {shift_type!r}")
