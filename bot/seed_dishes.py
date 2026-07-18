from __future__ import annotations

import json
import sqlite3

SEED_DISHES = [
    dict(
        name="Lentejas con chorizo",
        for_comida=1, for_cena=0, fresco=0, tupper=1, rapido=0, rendimiento=4, metodo="Fuego",
        ingredients=["300g lentejas", "1 cebolla", "2 zanahorias", "1 chorizo", "1 diente de ajo", "aceite de oliva", "sal", "pimentón"],
        steps=["Sofreír la cebolla, el ajo y la zanahoria picados", "Añadir el chorizo en rodajas y el pimentón",
               "Incorporar las lentejas y cubrir con agua", "Cocer a fuego lento 40 minutos", "Rectificar de sal"],
    ),
    dict(
        name="Crema de calabaza",
        for_comida=1, for_cena=1, fresco=0, tupper=1, rapido=0, rendimiento=4, metodo="Thermomix",
        ingredients=["800g calabaza", "1 puerro", "1 patata", "caldo de verduras", "sal", "aceite de oliva"],
        steps=["Trocear todas las verduras", "Poner en el vaso con el caldo", "Programar 25 min, 100°C, velocidad 1",
               "Triturar 1 min, velocidad progresiva 5-10"],
    ),
    dict(
        name="Pasta con atún",
        for_comida=1, for_cena=1, fresco=0, tupper=1, rapido=1, rendimiento=2, metodo="Fuego",
        ingredients=["300g pasta", "2 latas de atún", "salsa de tomate", "1 cebolla", "aceite de oliva"],
        steps=["Cocer la pasta según el paquete", "Sofreír la cebolla picada", "Añadir el tomate y el atún escurrido",
               "Mezclar con la pasta cocida"],
    ),
    dict(
        name="Arroz caldoso de verduras",
        for_comida=1, for_cena=0, fresco=0, tupper=1, rapido=0, rendimiento=3, metodo="Thermomix",
        ingredients=["300g arroz", "1 pimiento rojo", "1 calabacín", "2 zanahorias", "caldo de verduras", "azafrán o colorante"],
        steps=["Trocear las verduras y sofreír 10 min, varoma, velocidad cuchara",
               "Añadir el caldo y el arroz", "Programar 18 min, 100°C, giro a la izquierda, velocidad cuchara"],
    ),
    dict(
        name="Garbanzos salteados con espinacas",
        for_comida=0, for_cena=1, fresco=0, tupper=0, rapido=1, rendimiento=3, metodo="Fuego",
        ingredients=["2 botes de garbanzos cocidos", "300g espinacas frescas", "2 dientes de ajo", "pimentón", "aceite de oliva"],
        steps=["Dorar el ajo laminado en la sartén", "Añadir los garbanzos escurridos y saltear",
               "Incorporar las espinacas hasta que reduzcan", "Espolvorear pimentón al final"],
    ),
    dict(
        name="Salmón fresco al airfryer",
        for_comida=0, for_cena=1, fresco=1, tupper=0, rapido=1, rendimiento=1, metodo="Airfryer",
        ingredients=["1 lomo de salmón fresco", "limón", "aceite de oliva", "sal", "eneldo (opcional)"],
        steps=["Salpimentar el salmón y untar con aceite", "Airfryer 180°C, 8-10 minutos", "Servir con un chorro de limón"],
    ),
    dict(
        name="Merluza fresca al horno con verduras",
        for_comida=0, for_cena=1, fresco=1, tupper=0, rapido=0, rendimiento=1, metodo="Horno",
        ingredients=["2 rodajas de merluza fresca", "1 patata", "1 cebolla", "1 tomate", "vino blanco", "aceite de oliva"],
        steps=["Colocar las verduras cortadas en la bandeja y hornear 15 min a 200°C",
               "Añadir la merluza encima con un chorrito de vino blanco", "Hornear 15-18 minutos más"],
    ),
    dict(
        name="Pechuga de pollo fresca al airfryer",
        for_comida=0, for_cena=1, fresco=1, tupper=0, rapido=1, rendimiento=1, metodo="Airfryer",
        ingredients=["2 pechugas de pollo frescas", "especias al gusto", "aceite de oliva"],
        steps=["Adobar la pechuga con especias y aceite", "Airfryer 180°C, 12-15 minutos, dando la vuelta a mitad"],
    ),
]


def seed_if_empty(conn: sqlite3.Connection) -> int:
    """Inserta el catálogo de ejemplo si la tabla dishes está vacía. Devuelve cuántos platos insertó."""
    count = conn.execute("SELECT COUNT(*) FROM dishes").fetchone()[0]
    if count > 0:
        return 0

    for dish in SEED_DISHES:
        conn.execute(
            """INSERT INTO dishes
               (name, for_comida, for_cena, fresco, tupper, rapido, rendimiento, ingredients_json, steps_json, metodo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dish["name"], dish["for_comida"], dish["for_cena"], dish["fresco"], dish["tupper"],
                dish["rapido"], dish["rendimiento"], json.dumps(dish["ingredients"], ensure_ascii=False),
                json.dumps(dish["steps"], ensure_ascii=False), dish["metodo"],
            ),
        )
    conn.commit()
    return len(SEED_DISHES)
