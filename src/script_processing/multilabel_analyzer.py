"""
Multi-label sentiment & harassment classifier using Ollama or OpenRouter.

Reuses ChatProvider from sentiment_analyzer.py and applies the full multi-label
prompt from sentimiento_multietiqueta.py (6 categories + sentiment + confidence).
"""

import json
import time
from typing import Any

from script_processing.sentiment_analyzer import ChatProvider
from script_processing.sentimiento_dictionary import SENTIMIENTO_DICT

LABEL_KEYS = [
    "menosprecio",
    "cuerpo_y_sexualidad",
    "roles_y_genero",
    "amenazas",
    "acoso",
    "desprestigio",
]

EMPTY_LABELS = {k: False for k in LABEL_KEYS}


def make_prompt(batch: list[dict[str, str]], country: str = "Argentina") -> str:
    """Build the multi-label classification prompt for a batch of comments."""
    dictionary_block = json.dumps(SENTIMIENTO_DICT, ensure_ascii=False, indent=2)
    comments_block = "\n".join(
        f'{i + 1}) {{"id": "{item["id"]}", "comentario": "{item["text"]}"}}'
        for i, item in enumerate(batch)
    )

    return (
        "Rol:\n"
        f"Sos un asistente de clasificación de contenido para un proyecto de investigación sobre hostigamiento y discurso de odio en redes en {country}. "
        "Tu tarea es ETIQUETAR comentarios; no moderás, no reescribís, no mejorás el texto, no generás insultos nuevos ni completás términos ofensivos.\n\n"
        "Vas a recibir dos cosas:\n"
        "1) DICCIONARIO: una lista de términos/pistas agrupadas en 6 categorías.\n"
        f"2) COMENTARIOS: un lote de hasta {len(batch)} comentarios cortos con un id.\n\n"
        "Objetivo:\n"
        "Para cada comentario, determiná si corresponde (true/false) a cada una de estas categorías:\n"
        "- Menosprecio\n"
        "- Cuerpo y sexualidad\n"
        "- Roles y género\n"
        "- Amenazas\n"
        "- Acoso\n"
        "- Desprestigio\n\n"
        "Además, devolvé:\n"
        "- sentimiento discreto: positivo | neutro | negativo\n\n"
        "Importante:\n"
        "- Esto es CLASIFICACIÓN MULTI-ETIQUETA: un comentario puede tener varias categorías en true.\n"
        "- NO busques coincidencias exactas. Usá comprensión semántica: paráfrasis, insinuaciones, equivalentes.\n"
        "- El diccionario es una guía (pistas), NO una regla mecánica. Si aparece una palabra genérica del diccionario pero NO está dentro de una construcción hostil dirigida a alguien, NO etiquetes por eso.\n"
        "- Si el comentario es neutro, informativo o no está dirigido a atacar/hostigar/deslegitimar, dejá todas las etiquetas en false.\n"
        "- Si hay amenaza o incitación a violencia (física o sexual), marcá Amenazas=true siempre (aunque sea en chiste o en tono irónico).\n"
        "- Si hay violencia sexual como amenaza o coacción, marcá Amenazas=true y también Cuerpo y sexualidad=true.\n"
        "- Si el comentario cita una frase ofensiva para CONDENARLA explícitamente, en general NO etiquetes como ataque.\n"
        "- Si el comentario usa elogios/piropos para sexualizar u objetificar a una figura pública, o hace avances/pedidos intrusivos, marcá Acoso=true.\n\n"
        "Definiciones operativas:\n\n"
        "1) Menosprecio\n"
        "Ataque cuyo objetivo principal es humillar, ridiculizar o disminuir a la persona con insultos, burlas, descalificación de inteligencia/competencia o infantilización.\n\n"
        "2) Cuerpo y sexualidad\n"
        "Ataques, insultos o reducción de la persona por su cuerpo, apariencia o sexualidad; insultos sexualizados; ataques por orientación/identidad sexual usados como estigma.\n\n"
        "3) Roles y género\n"
        "Hostigamiento basado en estereotipos y mandatos de género: mandatos domésticos, policiamiento de maternidad/paternidad, o deslegitimación por salirse del rol esperado.\n\n"
        "4) Amenazas\n"
        "Intención, deseo o incitación a daño físico o sexual, muerte, desaparición, secuestro, violencia o intimidación coercitiva.\n\n"
        "5) Acoso\n"
        "Interacción intrusiva/no deseada dirigida a la persona: hostigamiento, avances romántico-sexuales, demandas de contacto/acción, piropos objetificantes, insistencia o cosificación.\n\n"
        "6) Desprestigio\n"
        "Ataques orientados a dañar credibilidad, reputación o legitimidad pública: acusaciones de delito/corrupción, etiquetas político-ideológicas estigmatizantes, deslegitimación moral/política.\n\n"
        "Formato de salida (OBLIGATORIO):\n"
        "Respondé SOLO con JSON válido, sin texto extra, sin markdown.\n\n"
        "Estructura:\n"
        "{\n"
        '  "results": [\n'
        "    {\n"
        '      "id": <id_del_comentario>,\n'
        '      "labels": {\n'
        '        "menosprecio": <true|false>,\n'
        '        "cuerpo_y_sexualidad": <true|false>,\n'
        '        "roles_y_genero": <true|false>,\n'
        '        "amenazas": <true|false>,\n'
        '        "acoso": <true|false>,\n'
        '        "desprestigio": <true|false>\n'
        "      },\n"
        '      "sentimiento": "<positivo|neutro|negativo>",\n'
        '      "confidence": <numero_entre_0_y_1>\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Checklist final antes de responder:\n"
        "- ¿Devolviste JSON válido y nada más?\n"
        "- ¿Mantuviste el orden de los comentarios?\n"
        "- ¿Amenazas=true ante cualquier indicio de daño físico/sexual?\n\n"
        "Ahora procesá los insumos:\n\n"
        "DICCIONARIO:\n"
        "<<<\n"
        f"{dictionary_block}\n"
        ">>>\n\n"
        "COMENTARIOS:\n"
        "<<<\n"
        f"{comments_block}\n"
        ">>>"
    )


def parse_json_from_text(text: str) -> dict[str, Any]:
    """Parse a JSON object from a model response, stripping markdown fences."""
    if text is None:
        raise ValueError("Empty model response")

    text = text.strip()

    # Strip Markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct JSON
    try:
        return json.loads(text)
    except Exception:
        pass

    # Fallback: extract first outermost object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1].strip()
        return json.loads(candidate)

    raise ValueError("No JSON found in model response")


def normalize_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single result entry to safe defaults."""
    labels = item.get("labels", {}) if isinstance(item, dict) else {}
    if not isinstance(labels, dict):
        labels = {}
    sentiment_raw = (
        str(item.get("sentimiento", "")).strip().lower() if isinstance(item, dict) else ""
    )
    sentiment = sentiment_raw if sentiment_raw in {"positivo", "neutro", "negativo"} else "neutro"
    try:
        confidence = float(item.get("confidence", 0.0)) if isinstance(item, dict) else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "labels": {k: bool(labels.get(k, False)) for k in LABEL_KEYS},
        "sentimiento": sentiment,
        "confidence": confidence,
    }


def extract_results_dict(
    parsed: dict[str, Any], expected_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Normalize model output to mapping id -> entry."""
    out: dict[str, dict[str, Any]] = {}
    results = parsed.get("results", []) if isinstance(parsed, dict) else []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id is None:
                continue
            out[str(item_id)] = normalize_entry(item)

    # Ensure all expected ids are present with safe defaults.
    for rid in expected_ids:
        if rid not in out:
            out[rid] = {
                "labels": dict(EMPTY_LABELS),
                "sentimiento": "neutro",
                "confidence": 0.0,
                "error": "missing_in_response",
            }

    return out


def call_provider(
    provider: ChatProvider,
    prompt_text: str,
    attempts: int = 3,
) -> str | None:
    """Call the chat provider with retries."""
    last_content = None
    for a in range(1, attempts + 1):
        try:
            content = provider.chat(messages=[{"role": "user", "content": prompt_text}])
            return content
        except Exception as e:
            print(f"Error llamando al modelo (intento {a}/{attempts}): {e}")
            time.sleep(1.5 * a)
            last_content = None
    return last_content


def classify_batch(
    provider: ChatProvider,
    batch_items: list[dict[str, str]],
    batch_label: str,
    country: str = "Argentina",
    debug_dir: str = ".",
) -> dict[str, dict[str, Any]]:
    """
    Classify a batch of items. On JSON parse failure, recursively split the batch
    in half and retry, down to individual items.
    """

    def try_once(items: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
        prompt = make_prompt(items, country=country)
        content = call_provider(provider, prompt, attempts=3)
        if not content:
            raise ValueError("Empty model response")
        try:
            parsed = parse_json_from_text(content)
        except Exception:
            retry_prompt = (
                prompt
                + "\n\nIMPORTANTE: Responde ÚNICAMENTE con un JSON válido con la estructura {'results':[...]}."
            )
            content2 = call_provider(provider, retry_prompt, attempts=2)
            if not content2:
                raise ValueError("Empty model response (retry)")
            parsed = parse_json_from_text(content2)
        expected = [str(x["id"]) for x in items]
        return extract_results_dict(parsed, expected)

    results_all: dict[str, dict[str, Any]] = {}
    stack: list[tuple[list[dict[str, str]], str]] = [(batch_items, batch_label)]

    while stack:
        items, label = stack.pop()
        try:
            j = try_once(items)
            results_all.update(j)
        except Exception as e:
            debug_path = f"{debug_dir}/debug_bad_json_batch_{label}.txt"
            try:
                with open(debug_path, "w", encoding="utf-8") as dfh:
                    dfh.write("\n\n".join(f"ID: {x['id']}\nTEXTO: {x['text']}" for x in items))
            except Exception:
                pass

            if len(items) > 1:
                mid = len(items) // 2
                left, right = items[:mid], items[mid:]
                stack.append((right, f"{label}b"))
                stack.append((left, f"{label}a"))
                print(
                    f"WARN: batch {label} devolvió JSON inválido ({e}). "
                    f"Dividiendo en {len(left)} y {len(right)}. Debug: {debug_path}"
                )
            else:
                bad_id = str(items[0].get("id"))
                results_all[bad_id] = {
                    "labels": dict(EMPTY_LABELS),
                    "sentimiento": "neutro",
                    "confidence": 0.0,
                    "error": "bad_json",
                }
                print(
                    f"WARN: item {bad_id} no pudo parsearse como JSON. "
                    f"Se marca vacío. Debug: {debug_path}"
                )

    return results_all
