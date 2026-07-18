import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from bot.shift_rules import slot_constraint


@pytest.mark.parametrize(
    "shift_type,meal_type,expected",
    [
        ("MT", "comida", "tupper"),
        ("MT", "cena", "rapido"),
        ("M", "comida", "rapido"),
        ("M", "cena", None),
        ("T", "comida", "rapido"),
        ("T", "cena", "rapido"),
        (None, "comida", None),
        (None, "cena", None),
    ],
)
def test_slot_constraint_table(shift_type, meal_type, expected):
    assert slot_constraint(shift_type, meal_type) == expected


def test_unknown_shift_type_raises():
    with pytest.raises(ValueError):
        slot_constraint("X", "comida")


def test_unknown_meal_type_raises():
    with pytest.raises(ValueError):
        slot_constraint("MT", "merienda")
