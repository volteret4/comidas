from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class Dish:
    id: int
    name: str
    for_comida: bool
    for_cena: bool
    fresco: bool
    tupper: bool
    rapido: bool
    rendimiento: int
    ingredients: list[str]
    steps: list[str] = field(default_factory=list)
    metodo: str | None = None
    source_url: str | None = None
    active: bool = True

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Dish":
        return cls(
            id=row["id"],
            name=row["name"],
            for_comida=bool(row["for_comida"]),
            for_cena=bool(row["for_cena"]),
            fresco=bool(row["fresco"]),
            tupper=bool(row["tupper"]),
            rapido=bool(row["rapido"]),
            rendimiento=row["rendimiento"],
            ingredients=json.loads(row["ingredients_json"]),
            steps=json.loads(row["steps_json"]) if row["steps_json"] else [],
            metodo=row["metodo"],
            source_url=row["source_url"],
            active=bool(row["active"]),
        )

    def has_tag(self, tag: str) -> bool:
        return {"tupper": self.tupper, "rapido": self.rapido, "fresco": self.fresco}[tag]


@dataclass
class PlanSlot:
    id: int
    weekly_plan_id: int
    slot_date: str
    meal_type: str
    shift_type: str | None
    dish_id: int | None
    batch_group_id: int | None
    resolved_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PlanSlot":
        return cls(
            id=row["id"],
            weekly_plan_id=row["weekly_plan_id"],
            slot_date=row["slot_date"],
            meal_type=row["meal_type"],
            shift_type=row["shift_type"],
            dish_id=row["dish_id"],
            batch_group_id=row["batch_group_id"],
            resolved_at=row["resolved_at"],
        )


@dataclass
class WeeklyPlan:
    id: int
    week_start_date: str
    status: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WeeklyPlan":
        return cls(
            id=row["id"],
            week_start_date=row["week_start_date"],
            status=row["status"],
        )


@dataclass
class Leftover:
    id: int
    dish_id: int
    meal_type: str
    remaining_days: int
    source_weekly_plan_id: int
    consumed: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Leftover":
        return cls(
            id=row["id"],
            dish_id=row["dish_id"],
            meal_type=row["meal_type"],
            remaining_days=row["remaining_days"],
            source_weekly_plan_id=row["source_weekly_plan_id"],
            consumed=bool(row["consumed"]),
        )
