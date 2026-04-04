import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Set

import pandas as pd
from openai import OpenAI

from sentimiento_dictionary import SENTIMIENTO_DICT

# ensure local module import works when running from repo root
sys.path.append(os.path.dirname(__file__))

# OpenAI client (lazy init)
client = None


def init_openai_client(cli_api_key: str = ""):
    """Create client from CLI key, env var, or local .env (if python-dotenv is installed)."""
    global client
    if client is not None:
        return client

    # Optional .env loading without hard dependency
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    api_key = (cli_api_key or "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY no configurada. Definila en el entorno, en .env, o pasala por --api-key."
        )

    client = OpenAI(api_key=api_key)
    return client


# ---- Data helpers ----
def load_replies_data(parquet_path: str, platform: str) -> pd.DataFrame:
    """Load replies from parquet and filter by platform if needed."""
    df = pd.read_parquet(parquet_path)
    if platform != "all":
        df = df[df["platform"].astype(str).str.lower() == platform].copy()
    return df


def build_out_paths(country: str, platform: str):
    """Return (out_dir, out_json, out_ndjson, out_timing, out_csv)."""
    out_dir = os.path.join("out", country, platform)
    os.makedirs(out_dir, exist_ok=True)

    suffix_map = {"twitter": "tw", "instagram": "ig", "youtube": "yt", "all": "all"}
    suffix = suffix_map.get(platform)
    if not suffix:
        raise ValueError(f"Plataforma no soportada para outputs: {platform}")

    out_json = os.path.join(out_dir, f"replies_llm_multilabel_{suffix}.json")
    out_ndjson = os.path.join(out_dir, f"replies_llm_multilabel_{suffix}.ndjson")
    out_timing = os.path.join(out_dir, f"replies_llm_multilabel_{suffix}_timing.json")
    out_csv = os.path.join(out_dir, f"replies_with_multilabels_{suffix}.csv")

    return out_dir, out_json, out_ndjson, out_timing, out_csv


def get_reply_id(row, idx):
    # try common id columns, otherwise fallback to index-based id
    for col in (
        "reply_id",
        "replyId",
        "id",
        "tweet_id",
        "replyid",
        "comment_id",
        "commentId",
        "comment_id_str",
        "video_id",
        "videoId",
    ):
        if col in row.index and not pd.isna(row[col]):
            return str(row[col])
    return f"row_{idx}"


def make_prompt(batch: List[Dict[str, str]], country: str = "Argentina") -> str:
    dictionary_block = json.dumps(SENTIMIENTO_DICT, ensure_ascii=False, indent=2)
    comments_block = "\n".join(
        [f'{i + 1}) {{"id": "{item["id"]}", "comentario": "{item["text"]}"}}' for i, item in enumerate(batch)]
    )

    return (
        "Rol:\n"
        f"Sos un asistente de clasificación de contenido para un proyecto de investigación sobre hostigamiento y discurso de odio en redes en {country}. "
        "Tu tarea es ETIQUETAR comentarios; no moderás, no reescribís, no “mejorás” el texto, no generás insultos nuevos ni completás términos ofensivos.\n\n"
        "Vas a recibir dos cosas:\n"
        "1) DICCIONARIO: una lista de términos/pistas agrupadas en 6 categorías.\n"
        "2) COMENTARIOS: un lote de hasta 80 comentarios cortos (≈140 caracteres) con un id.\n\n"
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
        "- NO busques coincidencias exactas. Usá comprensión semántica: paráfrasis, insinuaciones, equivalentes (“mandatos domésticos”, “descalificación”, “sexualización”, etc.).\n"
        "- El diccionario es una guía (pistas), NO una regla mecánica. Si aparece una palabra genérica del diccionario (ej. “saber”, “nada”, “plata”) pero NO está dentro de una construcción hostil dirigida a alguien, NO etiquetes por eso.\n"
        "- Si el comentario es neutro, informativo o no está dirigido a atacar/hostigar/deslegitimar, dejá todas las etiquetas en false.\n"
        "- Si hay amenaza o incitación a violencia (física o sexual), marcá Amenazas=true siempre (aunque sea “en chiste” o en tono irónico).\n"
        "- Si hay violencia sexual como amenaza o coacción, marcá Amenazas=true y también Cuerpo y sexualidad=true.\n"
        "- Si el comentario cita una frase ofensiva para CONDENARLA explícitamente (ej. “No le digan X”), en general NO etiquetes como ataque; si no queda claro que la está condenando (o la reproduce/impulsa), sí etiquetá.\n"
        "- Si el comentario usa elogios/“piropos” para sexualizar u objetificar a una figura pública, o hace avances/pedidos intrusivos, marcá Acoso=true (aunque el tono parezca “positivo”).\n\n"
        "Definiciones operativas (usá estas definiciones, además del diccionario):\n\n"
        "1) Menosprecio\n"
        "Ataque cuyo objetivo principal es humillar, ridiculizar o disminuir a la persona (o su capacidad/valor) con insultos, burlas, descalificación de inteligencia/competencia o infantilización.\n\n"
        "2) Cuerpo y sexualidad\n"
        "Ataques, insultos o reducción de la persona por su cuerpo, apariencia o sexualidad; insultos sexualizados; lenguaje explícito sexual usado para degradar; ataques por orientación/identidad sexual o expresión de género usados como estigma.\n\n"
        "3) Roles y género\n"
        "Hostigamiento basado en estereotipos y mandatos de género: “tu lugar es el hogar”, cocina/limpieza, “ocupate de tus hijos”, policiamiento de maternidad/paternidad, moralización del rol familiar, o deslegitimación por salirse del rol esperado.\n\n"
        "4) Amenazas\n"
        "Intención, deseo o incitación a daño físico o sexual, muerte, desaparición, secuestro, violencia o intimidación coercitiva (incluye vigilancia, “callate” como coerción, “te va a pasar…”, y violencia virtual, cancelacion, doxxing etc.).\n\n"
        "5) Acoso\n"
        "Interacción intrusiva/no deseada dirigida a la persona: hostigamiento, avances romántico-sexuales, demandas de contacto/acción, piropos objetificantes en contexto inapropiado, insistencia o cosificación.\n\n"
        "6) Desprestigio\n"
        "Ataques orientados a dañar credibilidad, reputación o legitimidad pública: acusaciones de delito/corrupción/robo, etiquetas político-ideológicas estigmatizantes, deslegitimación moral/política.\n\n"
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


def parse_json_from_text(text: str) -> Dict[str, Any]:
    """Parse a JSON object from a model response."""
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


def load_processed_ids_from_ndjson(path: str) -> Set[str]:
    """Read NDJSON where each line is a JSON object {id: {...}, ...} and return processed ids."""
    processed: Set[str] = set()
    if not os.path.exists(path):
        return processed
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    processed.update(str(k) for k in obj.keys())
            except Exception:
                continue
    return processed


def normalize_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    labels = item.get("labels", {}) if isinstance(item, dict) else {}
    if not isinstance(labels, dict):
        labels = {}
    sentiment_raw = str(item.get("sentimiento", "")).strip().lower() if isinstance(item, dict) else ""
    sentiment = sentiment_raw if sentiment_raw in {"positivo", "neutro", "negativo"} else "neutro"
    return {
        "labels": {
            "menosprecio": bool(labels.get("menosprecio", False)),
            "cuerpo_y_sexualidad": bool(labels.get("cuerpo_y_sexualidad", False)),
            "roles_y_genero": bool(labels.get("roles_y_genero", False)),
            "amenazas": bool(labels.get("amenazas", False)),
            "acoso": bool(labels.get("acoso", False)),
            "desprestigio": bool(labels.get("desprestigio", False)),
        },
        "sentimiento": sentiment,
        "confidence": float(item.get("confidence", 0.0)) if isinstance(item, dict) else 0.0,
    }


def extract_results_dict(parsed: Dict[str, Any], expected_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Normalize model output to mapping id -> entry."""
    out: Dict[str, Dict[str, Any]] = {}
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
                "labels": {
                    "menosprecio": False,
                    "cuerpo_y_sexualidad": False,
                    "roles_y_genero": False,
                    "amenazas": False,
                    "acoso": False,
                    "desprestigio": False,
                },
                "sentimiento": "neutro",
                "confidence": 0.0,
                "error": "missing_in_response",
            }

    return out


def classify_batches(
    df: pd.DataFrame,
    out_file_nd: str,
    out_file_timing: str,
    batch_size: int = 80,
    model: str = "gpt-4o-mini",
    country: str = "Argentina",
    max_workers: int = 8,
) -> Dict[str, Dict[str, Any]]:
    outputs: Dict[str, Dict[str, Any]] = {}
    batch_times: List[float] = []
    total_texts = len(df)

    # Resume support.
    processed_ids = load_processed_ids_from_ndjson(out_file_nd)
    if processed_ids:
        print(f"Resume: detectados {len(processed_ids)} IDs ya procesados en {out_file_nd}. Se van a saltear.")

    # Lock for thread-safe writes to NDJSON and shared state.
    write_lock = threading.Lock()

    def call_model(prompt_text: str, attempts: int = 3):
        last_content = None
        for a in range(1, attempts + 1):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt_text}],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                last_content = resp.choices[0].message.content
                return last_content
            except Exception as e:
                print(f"Error llamando al modelo (intento {a}/{attempts}): {e}")
                time.sleep(1.5 * a)
        return last_content

    def process_batch_with_fallback(batch_items: List[Dict[str, str]], batch_label: int):
        def try_once(items: List[Dict[str, str]]):
            prompt = make_prompt(items, country=country)
            content = call_model(prompt, attempts=3)
            if not content:
                raise ValueError("Empty model response")
            try:
                parsed = parse_json_from_text(content)
            except Exception:
                retry_prompt = (
                    prompt + "\n\nIMPORTANTE: Responde ÚNICAMENTE con un JSON válido con la estructura {'results':[...]}."
                )
                content2 = call_model(retry_prompt, attempts=2)
                if not content2:
                    raise ValueError("Empty model response (retry)")
                parsed = parse_json_from_text(content2)
            expected = [str(x["id"]) for x in items]
            return extract_results_dict(parsed, expected)

        results_all: Dict[str, Dict[str, Any]] = {}
        stack = [(batch_items, f"{batch_label}")]

        while stack:
            items, label = stack.pop()
            try:
                j = try_once(items)
                results_all.update(j)
            except Exception as e:
                debug_path = os.path.join(os.path.dirname(out_file_nd), f"debug_bad_json_batch_{label}.txt")
                try:
                    with open(debug_path, "w", encoding="utf-8") as dfh:
                        dfh.write("\n\n".join([f"ID: {x['id']}\nTEXTO: {x['text']}" for x in items]))
                except Exception:
                    pass

                if len(items) > 1:
                    mid = len(items) // 2
                    left = items[:mid]
                    right = items[mid:]
                    stack.append((right, f"{label}b"))
                    stack.append((left, f"{label}a"))
                    print(
                        f"WARN: batch {label} devolvió JSON inválido ({e}). Dividiendo en {len(left)} y {len(right)}. Debug: {debug_path}"
                    )
                else:
                    bad_id = str(items[0].get("id"))
                    results_all[bad_id] = {
                        "labels": {
                            "menosprecio": False,
                            "cuerpo_y_sexualidad": False,
                            "roles_y_genero": False,
                            "amenazas": False,
                            "acoso": False,
                            "desprestigio": False,
                        },
                        "sentimiento": "neutro",
                        "confidence": 0.0,
                        "error": "bad_json",
                    }
                    print(
                        f"WARN: item {bad_id} no pudo parsearse como JSON. Se marca vacío y se continúa. Debug: {debug_path}"
                    )
        return results_all

    # Build all batches upfront, skipping already-processed IDs.
    all_batches: List[List[Dict[str, str]]] = []
    current_batch: List[Dict[str, str]] = []

    for idx, row in df.iterrows():
        rid = get_reply_id(row, idx)
        if rid in processed_ids:
            continue

        text = None
        for tc in ("text", "textDisplay", "textOriginal", "comment", "message", "body"):
            if tc in row.index and not pd.isna(row[tc]):
                text = row[tc]
                break
        if text is None:
            text = row.values[0]

        current_batch.append({"id": rid, "text": str(text).replace('"', "'")})
        if len(current_batch) >= batch_size:
            all_batches.append(current_batch)
            current_batch = []
    if current_batch:
        all_batches.append(current_batch)

    total_batches = len(all_batches)
    processed_count = 0
    print(f"Batches a procesar: {total_batches} (con {max_workers} workers en paralelo)")

    def process_one(batch_idx: int, batch_items: List[Dict[str, str]]):
        t0 = time.time()
        j = process_batch_with_fallback(batch_items, batch_idx + 1)
        elapsed = time.time() - t0
        return batch_idx, j, elapsed

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_one, i, b): i
            for i, b in enumerate(all_batches)
        }
        for future in as_completed(futures):
            batch_idx, j, elapsed = future.result()
            batch_times.append(elapsed)

            with write_lock:
                processed_count += 1
                outputs.update(j)
                try:
                    with open(out_file_nd, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(j, ensure_ascii=False) + "\n")
                except Exception as e:
                    print(f"No se pudo guardar resultados intermedios: {e}")

                avg = sum(batch_times) / len(batch_times)
                remaining = total_batches - processed_count
                est_remaining = remaining * avg / max_workers
                print(
                    f"Batch {batch_idx + 1}/{total_batches} listo ({len(j)} IDs) | "
                    f"{elapsed:.1f}s | Promedio: {avg:.1f}s | "
                    f"Completados: {processed_count}/{total_batches} | "
                    f"Est. resto: {est_remaining:.0f}s"
                )

    try:
        timing = {
            "total_texts": total_texts,
            "batch_size": batch_size,
            "total_batches": total_batches,
            "processed_batches": processed_count,
            "max_workers": max_workers,
            "per_batch_seconds": batch_times,
            "average_seconds": sum(batch_times) / len(batch_times) if batch_times else 0.0,
            "total_seconds": sum(batch_times),
            "wall_clock_estimate": sum(batch_times) / max_workers if batch_times else 0.0,
        }
        with open(out_file_timing, "w", encoding="utf-8") as tf:
            json.dump(timing, tf, ensure_ascii=False, indent=2)
        print(f"Timing guardado en: {out_file_timing}")
    except Exception as e:
        print("No se pudo guardar timing:", e)

    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clasifica replies desde parquet por plataforma (twitter/instagram/youtube/all) usando formato multi-etiqueta y genera CSV."
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API key de OpenAI. Si no se pasa, usa OPENAI_API_KEY o .env",
    )
    parser.add_argument(
        "--country",
        default="argentina",
        help="País a procesar (se usa para construir el path GCS y los directorios de salida)",
    )
    parser.add_argument(
        "--parquet",
        default="",

    )
    parser.add_argument(
        "--platform",
        choices=["twitter", "instagram", "youtube", "all"],
        default="twitter",
        help="Plataforma a procesar (o all para las tres juntas)",
    )
    parser.add_argument(
        "--run-llm",
        action="store_true",
        help="Ejecuta la clasificación con el modelo (costo $$). Por defecto NO se llama al LLM.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Permite sobrescribir outputs existentes (.json / .ndjson / timing).",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Limitar a N filas (para testing). 0 = sin límite.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Número de workers paralelos para llamadas al LLM (default: 8).",
    )
    parser.add_argument(
        "--exclude-youtube",
        action="store_true",
        help="Excluir YouTube al usar --platform all (solo procesa twitter + instagram).",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    country = args.country.lower()
    if args.parquet:
        parquet_path = args.parquet
    else:
        gcs_bucket_name = os.getenv("GCS_BUCKET_NAME", "").strip()
        if not gcs_bucket_name:
            print(
                "ERROR: falta configurar GCS_BUCKET_NAME (en el entorno o en .env) para construir el path GCS por defecto. "
                "Alternativa: pasá --parquet con una ruta explícita."
            )
            sys.exit(1)
        parquet_path = f"gs://{gcs_bucket_name}/data_analysis/{country}/replies.parquet"
    print(f"País: {country} | Parquet: {parquet_path}")

    df = load_replies_data(parquet_path, args.platform)
    if args.exclude_youtube and args.platform == "all":
        before = len(df)
        df = df[df["platform"].astype(str).str.lower() != "youtube"].copy()
        print(f"Excluido YouTube: {before} -> {len(df)} filas")
    if args.max_rows > 0:
        df = df.head(args.max_rows)
        print(f"Limitado a {len(df)} filas (--max-rows {args.max_rows})")
    out_dir, out_json, out_ndjson, out_timing, out_csv = build_out_paths(country, args.platform)

    if args.run_llm:
        try:
            init_openai_client(args.api_key)
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)

        if (os.path.exists(out_json) or os.path.exists(out_ndjson) or os.path.exists(out_timing)) and not args.overwrite:
            print(
                "ERROR: ya existen outputs para esta plataforma. "
                "Usá --overwrite si querés sobrescribir (ojo: esto puede costar $$ si re-ejecutás el LLM).\n"
                f"- {out_json}\n- {out_ndjson}\n- {out_timing}"
            )
            sys.exit(1)

        print(f"Total textos a clasificar ({args.platform}): {len(df)}")
        results = classify_batches(
            df,
            out_file_nd=out_ndjson,
            out_file_timing=out_timing,
            batch_size=80,
            model="gpt-4o-mini",
            country=country.title(),
            max_workers=args.max_workers,
        )
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print(f"Resultados guardados en: {out_json}")

    # Load LLM results: prefer NDJSON (append-safe, survives interruptions),
    # fall back to JSON if NDJSON is missing.
    llm_results: Dict[str, Any] = {}
    if os.path.exists(out_ndjson):
        with open(out_ndjson, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        llm_results.update(obj)
                except Exception:
                    continue
        print(f"Resultados cargados desde NDJSON: {len(llm_results)} IDs ({out_ndjson})")
    elif os.path.exists(out_json):
        with open(out_json, "r", encoding="utf-8") as fh:
            llm_results = json.load(fh)
        print(f"Resultados cargados desde JSON: {len(llm_results)} IDs ({out_json})")
    else:
        print(
            f"No se encontró archivo de resultados LLM en:\n"
            f"  - {out_ndjson}\n"
            f"  - {out_json}\n"
            "Opciones:\n"
            "1) Si YA generaste los resultados en otro lugar, movelos a esa ruta.\n"
            "2) Si querés generarlos ahora, ejecutá con: --run-llm (esto cuesta $$).\n"
        )
        sys.exit(1)

    # Output columns
    cat_map = {
        "menosprecio": "Menosprecio",
        "cuerpo_y_sexualidad": "Cuerpo y sexualidad",
        "roles_y_genero": "Roles y género",
        "amenazas": "Amenazas",
        "acoso": "Acoso",
        "desprestigio": "Desprestigio",
    }
    for out_col in cat_map.values():
        df[out_col] = 0
    df["classified_reply_id"] = None
    df["classified_sentimiento"] = "neutro"
    df["classified_confidence"] = 0.0

    for idx, row in df.iterrows():
        rid = get_reply_id(row, idx)
        df.at[idx, "classified_reply_id"] = rid
        entry = llm_results.get(rid) or llm_results.get(str(rid)) or llm_results.get(f"row_{idx}") or {}
        labels = entry.get("labels", {}) if isinstance(entry, dict) else {}

        for in_key, out_col in cat_map.items():
            if bool(labels.get(in_key, False)):
                df.at[idx, out_col] = 1

        df.at[idx, "classified_sentimiento"] = str(entry.get("sentimiento", "neutro")).lower()

        try:
            df.at[idx, "classified_confidence"] = float(entry.get("confidence", 0.0))
        except Exception:
            df.at[idx, "classified_confidence"] = 0.0

    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"Archivo con etiquetas guardado en: {out_csv}")
