from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from .config import config

logger = logging.getLogger(__name__)

MAX_PAGE_CHARS = 15000
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; comidas-bot/1.0; recipe-import)"

EXTRACTION_PROMPT = """Eres un asistente que extrae recetas de cocina a partir del texto de una página web.
Te doy el texto (ya extraído de HTML, puede incluir menús/publicidad irrelevante que debes ignorar) de una receta.
Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin explicaciones adicionales:

{{
  "name": "nombre corto del plato",
  "ingredients": ["ingrediente 1 con cantidad", "ingrediente 2 con cantidad", ...],
  "steps": ["paso 1", "paso 2", ...],
  "metodo_sugerido": "Thermomix" | "Airfryer" | "Fuego" | "Horno" | "Ninguno",
  "fresco_sugerido": true o false (true solo si el ingrediente principal es carne o pescado fresco que debe cocinarse el mismo día),
  "tupper_sugerido": true o false (true si el plato es apto para llevar en tupper al trabajo),
  "rapido_sugerido": true o false (true si se prepara/recalienta en poco tiempo),
  "rendimiento_sugerido": número entero de días de ración que suele rendir esta cantidad si no es fresco (usa 1 si es fresco)
}}

Texto de la página:
---
{page_text}
---
"""


class RecipeExtractionError(Exception):
    pass


@dataclass
class ExtractedRecipe:
    name: str
    ingredients: list[str]
    steps: list[str] = field(default_factory=list)
    metodo_sugerido: str | None = None
    fresco_sugerido: bool = False
    tupper_sugerido: bool = False
    rapido_sugerido: bool = False
    rendimiento_sugerido: int = 1


def _fetch_page_text(url: str) -> str:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RecipeExtractionError(f"No se pudo descargar el enlace: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    if not text:
        raise RecipeExtractionError("La página no tiene texto legible")
    return text[:MAX_PAGE_CHARS]


def extract_recipe(url: str) -> ExtractedRecipe:
    if not config.gemini_api_key:
        raise RecipeExtractionError("Falta GEMINI_API_KEY en la configuración del bot")

    page_text = _fetch_page_text(url)

    client = genai.Client(api_key=config.gemini_api_key)
    try:
        response = client.models.generate_content(
            model=config.gemini_model,
            contents=EXTRACTION_PROMPT.format(page_text=page_text),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=8192,
            ),
        )
    except Exception as exc:  # errores de red/API de Gemini (incluida cuota agotada), no queremos tumbar el bot
        raise RecipeExtractionError(f"Fallo al llamar a Gemini: {exc}") from exc

    finish_reason = None
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        finish_reason = str(getattr(candidates[0], "finish_reason", "") or "")
    if finish_reason and finish_reason.upper() not in ("STOP", "FINISH_REASON_UNSPECIFIED", ""):
        raise RecipeExtractionError(
            f"Gemini cortó la respuesta antes de terminar ({finish_reason}). "
            "Puede ser por la cuota gratuita agotada o por una receta demasiado larga; "
            "espera un rato o inténtalo con otro enlace."
        )

    if not response.text:
        raise RecipeExtractionError(
            "Gemini no devolvió ningún contenido (puede ser la cuota gratuita agotada). Prueba de nuevo más tarde."
        )

    try:
        data = json.loads(response.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RecipeExtractionError(
            f"Gemini no devolvió JSON válido, probablemente la respuesta se cortó por cuota o límite de tamaño: {exc}"
        ) from exc

    name = str(data.get("name") or "").strip()
    ingredients = [str(i).strip() for i in data.get("ingredients") or [] if str(i).strip()]
    if not name or not ingredients:
        raise RecipeExtractionError("No se pudieron extraer nombre e ingredientes de la receta")

    return ExtractedRecipe(
        name=name,
        ingredients=ingredients,
        steps=[str(s).strip() for s in data.get("steps") or [] if str(s).strip()],
        metodo_sugerido=(str(data.get("metodo_sugerido")).strip() or None) if data.get("metodo_sugerido") else None,
        fresco_sugerido=bool(data.get("fresco_sugerido", False)),
        tupper_sugerido=bool(data.get("tupper_sugerido", False)),
        rapido_sugerido=bool(data.get("rapido_sugerido", False)),
        rendimiento_sugerido=max(1, int(data.get("rendimiento_sugerido") or 1)),
    )
