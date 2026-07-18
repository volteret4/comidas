from __future__ import annotations

import json
import logging
from enum import IntEnum, auto

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .. import gemini_client
from ..db import get_connection
from ..gemini_client import RecipeExtractionError
from ..models import Dish

logger = logging.getLogger(__name__)

TAG_LABELS = {"fresco": "Fresco", "tupper": "Tupper", "rapido": "Rápido"}


class State(IntEnum):
    NAME = auto()
    URL_INPUT = auto()
    REVIEW_EXTRACTION = auto()
    REVIEW_NAME = auto()
    MEAL_TYPE = auto()
    TAGS = auto()
    RENDIMIENTO = auto()
    INGREDIENTS = auto()
    STEPS = auto()
    CONFIRM = auto()
    EDIT_PICK = auto()
    EDIT_FIELD = auto()
    EDIT_VALUE = auto()
    EDIT_MEALTYPE = auto()
    EDIT_TAGS = auto()


def _empty_draft() -> dict:
    return {
        "name": None,
        "ingredients": [],
        "steps": [],
        "metodo": None,
        "source_url": None,
        "for_comida": False,
        "for_cena": False,
        "fresco": False,
        "tupper": False,
        "rapido": False,
        "rendimiento": 1,
    }


# ---------------------------------------------------------------------------
# /addplato — alta manual
# ---------------------------------------------------------------------------

async def addplato_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["dish_draft"] = _empty_draft()
    await update.message.reply_text("¿Cómo se llama el plato?")
    return State.NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["dish_draft"]["name"] = update.message.text.strip()
    return await _ask_meal_type(update.message.reply_text, context)


# ---------------------------------------------------------------------------
# /addplatourl — alta a partir de un enlace, vía Gemini
# ---------------------------------------------------------------------------

async def addplatourl_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["dish_draft"] = _empty_draft()
    if context.args:
        return await _extract_and_review(update.message.reply_text, context, context.args[0].strip())
    await update.message.reply_text("Envíame el enlace de la receta.")
    return State.URL_INPUT


async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _extract_and_review(update.message.reply_text, context, update.message.text.strip())


async def _extract_and_review(reply, context: ContextTypes.DEFAULT_TYPE, url: str) -> int:
    await reply("Leyendo la receta y extrayendo ingredientes y pasos, un momento...")
    try:
        recipe = gemini_client.extract_recipe(url)
    except RecipeExtractionError as exc:
        await reply(f"No he podido extraer la receta de ese enlace: {exc}\nPuedes darlo de alta a mano con /addplato.")
        return ConversationHandler.END

    draft = context.user_data["dish_draft"]
    draft["name"] = recipe.name
    draft["ingredients"] = recipe.ingredients
    draft["steps"] = recipe.steps
    draft["metodo"] = recipe.metodo_sugerido
    draft["source_url"] = url
    draft["fresco"] = recipe.fresco_sugerido
    draft["tupper"] = recipe.tupper_sugerido
    draft["rapido"] = recipe.rapido_sugerido
    draft["rendimiento"] = recipe.rendimiento_sugerido

    summary = _format_extraction_summary(draft)
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Continuar", callback_data="d:review:continue")],
            [InlineKeyboardButton("✏️ Cambiar nombre", callback_data="d:review:rename")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="d:review:cancel")],
        ]
    )
    await reply(summary, reply_markup=keyboard)
    return State.REVIEW_EXTRACTION


def _format_extraction_summary(draft: dict) -> str:
    lines = [f"He extraído esto de la receta:", "", f"*{draft['name']}*", ""]
    lines.append("Ingredientes:")
    lines.extend(f"  - {i}" for i in draft["ingredients"])
    if draft["steps"]:
        lines.append("")
        lines.append("Pasos:")
        lines.extend(f"  {n}. {s}" for n, s in enumerate(draft["steps"], 1))
    lines.append("")
    lines.append(f"Método sugerido: {draft['metodo'] or 'sin especificar'}")
    return "\n".join(lines)


async def review_extraction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[-1]

    if action == "cancel":
        await query.edit_message_text("Alta de plato cancelada.")
        return ConversationHandler.END

    if action == "rename":
        await query.edit_message_text("¿Qué nombre le pones?")
        return State.REVIEW_NAME

    return await _ask_meal_type(lambda text, **kw: query.edit_message_text(text, **kw), context)


async def receive_review_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["dish_draft"]["name"] = update.message.text.strip()
    return await _ask_meal_type(update.message.reply_text, context)


# ---------------------------------------------------------------------------
# Estados compartidos: tipo de comida, etiquetas, rendimiento, ingredientes, pasos, confirmación
# ---------------------------------------------------------------------------

async def _ask_meal_type(reply, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Comida", callback_data="d:mealtype:comida"),
                InlineKeyboardButton("Cena", callback_data="d:mealtype:cena"),
                InlineKeyboardButton("Ambas", callback_data="d:mealtype:ambas"),
            ]
        ]
    )
    await reply("¿Para comida, cena, o ambas?", reply_markup=keyboard)
    return State.MEAL_TYPE


async def meal_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[-1]
    draft = context.user_data["dish_draft"]
    draft["for_comida"] = choice in ("comida", "ambas")
    draft["for_cena"] = choice in ("cena", "ambas")
    return await _render_tags(query, context)


def _tags_keyboard(draft: dict, prefix: str = "d:tag") -> InlineKeyboardMarkup:
    def label(tag: str) -> str:
        mark = "☑" if draft[tag] else "☐"
        return f"{mark} {TAG_LABELS[tag]}"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label("fresco"), callback_data=f"{prefix}:fresco")],
            [InlineKeyboardButton(label("tupper"), callback_data=f"{prefix}:tupper")],
            [InlineKeyboardButton(label("rapido"), callback_data=f"{prefix}:rapido")],
            [InlineKeyboardButton("Listo ➡️", callback_data=f"{prefix}sdone")],
        ]
    )


async def _render_tags(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["dish_draft"]
    await query.edit_message_text(
        "Marca las etiquetas que apliquen (fresco = carne/pescado fresco, se cocina el mismo día):",
        reply_markup=_tags_keyboard(draft),
    )
    return State.TAGS


async def tag_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    tag = query.data.split(":")[-1]
    draft = context.user_data["dish_draft"]
    draft[tag] = not draft[tag]
    if draft["fresco"]:
        draft["tupper"] = False
    await query.edit_message_reply_markup(reply_markup=_tags_keyboard(draft))
    return State.TAGS


async def tags_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    draft = context.user_data["dish_draft"]

    if draft["fresco"]:
        draft["rendimiento"] = 1
        if draft["ingredients"]:
            return await _go_to_confirm_or_steps(query.edit_message_text, context)
        await query.edit_message_text("Envía la lista de ingredientes, uno por línea.")
        return State.INGREDIENTS

    suggested = draft.get("rendimiento") or 1
    await query.edit_message_text(f"¿Para cuántos días rinde una tanda de este plato? (sugerido: {suggested})")
    return State.RENDIMIENTO


async def receive_rendimiento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("Dime un número entero de 1 o más.")
        return State.RENDIMIENTO
    context.user_data["dish_draft"]["rendimiento"] = int(text)

    draft = context.user_data["dish_draft"]
    if draft["ingredients"]:
        return await _go_to_confirm_or_steps(update.message.reply_text, context)
    await update.message.reply_text("Envía la lista de ingredientes, uno por línea.")
    return State.INGREDIENTS


async def receive_ingredients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lines = [line.strip() for line in update.message.text.splitlines() if line.strip()]
    if not lines:
        await update.message.reply_text("Necesito al menos un ingrediente, uno por línea.")
        return State.INGREDIENTS
    context.user_data["dish_draft"]["ingredients"] = lines
    await update.message.reply_text("Envía los pasos a seguir, uno por línea (o envía - si no quieres detallarlos).")
    return State.STEPS


async def receive_steps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text != "-":
        context.user_data["dish_draft"]["steps"] = [line.strip() for line in text.splitlines() if line.strip()]
    return await _show_confirm(update.message.reply_text, context)


async def _go_to_confirm_or_steps(reply, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _show_confirm(reply, context)


async def _show_confirm(reply, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["dish_draft"]
    tags = ", ".join(TAG_LABELS[t] for t in ("fresco", "tupper", "rapido") if draft[t]) or "ninguna"
    meal = "comida y cena" if draft["for_comida"] and draft["for_cena"] else ("comida" if draft["for_comida"] else "cena")
    lines = [
        f"*{draft['name']}*",
        f"Para: {meal}",
        f"Etiquetas: {tags}",
        f"Rendimiento: {draft['rendimiento']} día(s)",
        f"Método: {draft['metodo'] or 'sin especificar'}",
        "Ingredientes:",
    ]
    lines.extend(f"  - {i}" for i in draft["ingredients"])
    if draft["steps"]:
        lines.append("Pasos:")
        lines.extend(f"  {n}. {s}" for n, s in enumerate(draft["steps"], 1))

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💾 Guardar", callback_data="d:confirm:save"),
                InlineKeyboardButton("❌ Cancelar", callback_data="d:confirm:cancel"),
            ]
        ]
    )
    await reply("\n".join(lines), reply_markup=keyboard)
    return State.CONFIRM


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[-1]

    if action == "cancel":
        await query.edit_message_text("Alta de plato cancelada.")
        context.user_data.pop("dish_draft", None)
        return ConversationHandler.END

    draft = context.user_data["dish_draft"]
    conn = get_connection()
    conn.execute(
        """INSERT INTO dishes
           (name, for_comida, for_cena, fresco, tupper, rapido, rendimiento,
            ingredients_json, steps_json, metodo, source_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            draft["name"], int(draft["for_comida"]), int(draft["for_cena"]), int(draft["fresco"]),
            int(draft["tupper"]), int(draft["rapido"]), draft["rendimiento"],
            json.dumps(draft["ingredients"], ensure_ascii=False), json.dumps(draft["steps"], ensure_ascii=False),
            draft["metodo"], draft["source_url"],
        ),
    )
    conn.commit()
    await query.edit_message_text(f"Guardado: {draft['name']} ✅")
    context.user_data.pop("dish_draft", None)
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("dish_draft", None)
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /listaplatos
# ---------------------------------------------------------------------------

async def listaplatos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM dishes WHERE active=1 ORDER BY name COLLATE NOCASE").fetchall()
    if not rows:
        await update.message.reply_text("No tienes ningún plato dado de alta todavía. Usa /addplato o /addplatourl.")
        return

    lines = []
    for row in rows:
        tags = "".join(
            [
                "🥩" if row["fresco"] else "",
                "🥡" if row["tupper"] else "",
                "⚡" if row["rapido"] else "",
            ]
        )
        meal = "🍽️" if row["for_comida"] else ""
        meal += "🌙" if row["for_cena"] else ""
        lines.append(f"#{row['id']} {row['name']} {meal} {tags} (rinde {row['rendimiento']}d)")
    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /verplato — receta completa (ingredientes y pasos) de un plato
# ---------------------------------------------------------------------------

async def verplato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_connection()
    query_text = " ".join(context.args).strip() if context.args else ""

    if query_text.isdigit():
        row = conn.execute("SELECT * FROM dishes WHERE id=? AND active=1", (int(query_text),)).fetchone()
        if row is None:
            await update.message.reply_text("No encuentro ningún plato activo con ese número.")
            return
        await update.message.reply_text(_format_dish_detail(row))
        return

    if query_text:
        rows = conn.execute(
            "SELECT id, name FROM dishes WHERE active=1 AND name LIKE ? ORDER BY name COLLATE NOCASE",
            (f"%{query_text}%",),
        ).fetchall()
        if not rows:
            await update.message.reply_text("No encuentro ningún plato activo con ese nombre.")
            return
    else:
        rows = conn.execute("SELECT id, name FROM dishes WHERE active=1 ORDER BY name COLLATE NOCASE").fetchall()
        if not rows:
            await update.message.reply_text("No tienes ningún plato dado de alta todavía.")
            return

    if len(rows) == 1:
        row = conn.execute("SELECT * FROM dishes WHERE id=?", (rows[0]["id"],)).fetchone()
        await update.message.reply_text(_format_dish_detail(row))
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(row["name"], callback_data=f"d:view:{row['id']}")] for row in rows]
    )
    await update.message.reply_text("¿Qué plato quieres ver?", reply_markup=keyboard)


async def verplato_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    dish_id = int(query.data.split(":")[-1])
    conn = get_connection()
    row = conn.execute("SELECT * FROM dishes WHERE id=?", (dish_id,)).fetchone()
    if row is None:
        await query.edit_message_text("Ese plato ya no existe.")
        return
    await query.edit_message_text(_format_dish_detail(row))


def _format_dish_detail(row) -> str:
    dish = Dish.from_row(row)
    meal = "comida y cena" if dish.for_comida and dish.for_cena else ("comida" if dish.for_comida else "cena")
    tags = ", ".join(TAG_LABELS[t] for t in ("fresco", "tupper", "rapido") if dish.has_tag(t)) or "ninguna"

    lines = [
        f"*{dish.name}* (#{dish.id})",
        f"Para: {meal}",
        f"Etiquetas: {tags}",
        f"Rendimiento: {dish.rendimiento} día(s)",
        f"Método: {dish.metodo or 'sin especificar'}",
        "",
        "Ingredientes:",
    ]
    lines.extend(f"  - {i}" for i in dish.ingredients)
    if dish.steps:
        lines.append("")
        lines.append("Pasos:")
        lines.extend(f"  {n}. {s}" for n, s in enumerate(dish.steps, 1))
    if dish.source_url:
        lines.append("")
        lines.append(f"Receta original: {dish.source_url}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /borrarplato
# ---------------------------------------------------------------------------

async def borrarplato_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_connection()
    rows = conn.execute("SELECT id, name FROM dishes WHERE active=1 ORDER BY name COLLATE NOCASE").fetchall()
    if not rows:
        await update.message.reply_text("No tienes ningún plato para borrar.")
        return
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(row["name"], callback_data=f"d:del:{row['id']}")] for row in rows]
    )
    await update.message.reply_text("¿Qué plato quieres borrar?", reply_markup=keyboard)


async def borrarplato_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    dish_id = int(query.data.split(":")[-1])
    conn = get_connection()
    row = conn.execute("SELECT name FROM dishes WHERE id=?", (dish_id,)).fetchone()
    conn.execute("UPDATE dishes SET active=0 WHERE id=?", (dish_id,))
    conn.commit()
    await query.edit_message_text(f"Borrado: {row['name'] if row else dish_id} ✅")


# ---------------------------------------------------------------------------
# /editplato — edición simple, un campo a la vez
# ---------------------------------------------------------------------------

EDITABLE_FIELDS = {
    "name": "Nombre",
    "mealtype": "Tipo de comida",
    "tags": "Etiquetas",
    "ingredients": "Ingredientes",
    "steps": "Pasos",
    "metodo": "Método",
    "rendimiento": "Rendimiento",
}


async def editplato_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    conn = get_connection()
    rows = conn.execute("SELECT id, name FROM dishes WHERE active=1 ORDER BY name COLLATE NOCASE").fetchall()
    if not rows:
        await update.message.reply_text("No tienes ningún plato para editar.")
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(row["name"], callback_data=f"d:editpick:{row['id']}")] for row in rows]
    )
    await update.message.reply_text("¿Qué plato quieres editar?", reply_markup=keyboard)
    return State.EDIT_PICK


async def edit_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    dish_id = int(query.data.split(":")[-1])
    context.user_data["edit_dish_id"] = dish_id
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"d:editfield:{field}")] for field, label in EDITABLE_FIELDS.items()]
    )
    await query.edit_message_text("¿Qué quieres cambiar?", reply_markup=keyboard)
    return State.EDIT_FIELD


async def edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[-1]
    context.user_data["edit_field"] = field
    dish_id = context.user_data["edit_dish_id"]

    if field == "mealtype":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Comida", callback_data="d:editmealtype:comida"),
                    InlineKeyboardButton("Cena", callback_data="d:editmealtype:cena"),
                    InlineKeyboardButton("Ambas", callback_data="d:editmealtype:ambas"),
                ]
            ]
        )
        await query.edit_message_text("¿Para comida, cena, o ambas?", reply_markup=keyboard)
        return State.EDIT_MEALTYPE

    if field == "tags":
        conn = get_connection()
        row = conn.execute("SELECT fresco, tupper, rapido FROM dishes WHERE id=?", (dish_id,)).fetchone()
        draft = {"fresco": bool(row["fresco"]), "tupper": bool(row["tupper"]), "rapido": bool(row["rapido"])}
        context.user_data["edit_tags_draft"] = draft
        await query.edit_message_text("Marca las etiquetas:", reply_markup=_tags_keyboard(draft, prefix="d:etag"))
        return State.EDIT_TAGS

    prompts = {
        "name": "Nuevo nombre:",
        "ingredients": "Nueva lista de ingredientes, uno por línea:",
        "steps": "Nuevos pasos, uno por línea (o - para vaciar):",
        "metodo": "Nuevo método (Thermomix / Airfryer / Fuego / Horno / etc.):",
        "rendimiento": "Nuevo rendimiento (días, entero >= 1):",
    }
    await query.edit_message_text(prompts[field])
    return State.EDIT_VALUE


async def edit_mealtype_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[-1]
    dish_id = context.user_data["edit_dish_id"]
    conn = get_connection()
    conn.execute(
        "UPDATE dishes SET for_comida=?, for_cena=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (int(choice in ("comida", "ambas")), int(choice in ("cena", "ambas")), dish_id),
    )
    conn.commit()
    await query.edit_message_text("Actualizado ✅")
    context.user_data.pop("edit_dish_id", None)
    return ConversationHandler.END


async def edit_tag_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    tag = query.data.split(":")[-1]
    draft = context.user_data["edit_tags_draft"]
    draft[tag] = not draft[tag]
    if draft["fresco"]:
        draft["tupper"] = False
    await query.edit_message_reply_markup(reply_markup=_tags_keyboard(draft, prefix="d:etag"))
    return State.EDIT_TAGS


async def edit_tags_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    draft = context.user_data.pop("edit_tags_draft")
    dish_id = context.user_data["edit_dish_id"]
    conn = get_connection()
    conn.execute(
        "UPDATE dishes SET fresco=?, tupper=?, rapido=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (int(draft["fresco"]), int(draft["tupper"]), int(draft["rapido"]), dish_id),
    )
    conn.commit()
    await query.edit_message_text("Actualizado ✅")
    context.user_data.pop("edit_dish_id", None)
    return ConversationHandler.END


async def edit_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    field = context.user_data["edit_field"]
    dish_id = context.user_data["edit_dish_id"]
    text = update.message.text.strip()
    conn = get_connection()

    if field == "ingredients":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            await update.message.reply_text("Necesito al menos un ingrediente.")
            return State.EDIT_VALUE
        conn.execute("UPDATE dishes SET ingredients_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (json.dumps(lines, ensure_ascii=False), dish_id))
    elif field == "steps":
        steps = [] if text == "-" else [line.strip() for line in text.splitlines() if line.strip()]
        conn.execute("UPDATE dishes SET steps_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (json.dumps(steps, ensure_ascii=False), dish_id))
    elif field == "rendimiento":
        if not text.isdigit() or int(text) < 1:
            await update.message.reply_text("Dime un número entero de 1 o más.")
            return State.EDIT_VALUE
        conn.execute("UPDATE dishes SET rendimiento=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(text), dish_id))
    elif field == "name":
        conn.execute("UPDATE dishes SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (text, dish_id))
    elif field == "metodo":
        conn.execute("UPDATE dishes SET metodo=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (text, dish_id))

    conn.commit()
    await update.message.reply_text("Actualizado ✅")
    context.user_data.pop("edit_dish_id", None)
    context.user_data.pop("edit_field", None)
    return ConversationHandler.END


# ---------------------------------------------------------------------------

def register(application: Application) -> None:
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("addplato", addplato_start),
            CommandHandler("addplatourl", addplatourl_start),
        ],
        states={
            State.NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            State.URL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)],
            State.REVIEW_EXTRACTION: [CallbackQueryHandler(review_extraction_callback, pattern="^d:review:")],
            State.REVIEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_review_name)],
            State.MEAL_TYPE: [CallbackQueryHandler(meal_type_callback, pattern="^d:mealtype:")],
            State.TAGS: [
                CallbackQueryHandler(tag_toggle_callback, pattern="^d:tag:"),
                CallbackQueryHandler(tags_done_callback, pattern="^d:tagsdone$"),
            ],
            State.RENDIMIENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_rendimiento)],
            State.INGREDIENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ingredients)],
            State.STEPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_steps)],
            State.CONFIRM: [CallbackQueryHandler(confirm_callback, pattern="^d:confirm:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("editplato", editplato_start)],
        states={
            State.EDIT_PICK: [CallbackQueryHandler(edit_pick_callback, pattern="^d:editpick:")],
            State.EDIT_FIELD: [CallbackQueryHandler(edit_field_callback, pattern="^d:editfield:")],
            State.EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value_received)],
            State.EDIT_MEALTYPE: [CallbackQueryHandler(edit_mealtype_callback, pattern="^d:editmealtype:")],
            State.EDIT_TAGS: [
                CallbackQueryHandler(edit_tag_toggle_callback, pattern="^d:etag:"),
                CallbackQueryHandler(edit_tags_done_callback, pattern="^d:etagsdone$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    application.add_handler(add_conv)
    application.add_handler(edit_conv)
    application.add_handler(CommandHandler("listaplatos", listaplatos))
    application.add_handler(CommandHandler("verplato", verplato))
    application.add_handler(CallbackQueryHandler(verplato_callback, pattern="^d:view:"))
    application.add_handler(CommandHandler("borrarplato", borrarplato_start))
    application.add_handler(CallbackQueryHandler(borrarplato_callback, pattern="^d:del:"))
