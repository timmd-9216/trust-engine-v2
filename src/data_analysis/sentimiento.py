import os
import sys
import json
import time
import math
import pandas as pd
from sentimiento_dictionary import SENTIMIENTO_DICT
from openai import OpenAI
import argparse
from typing import Set

# ensure local module import works when running from repo root
sys.path.append(os.path.dirname(__file__))
# OpenAI client (reads OPENAI_API_KEY from env)
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else OpenAI()

# ---- Platform helpers ----
def load_replies_sheet(excel_path: str, platform: str) -> pd.DataFrame:
    """Load the correct sheet based on platform."""
    sheet_map = {
        "twitter": "replies_tw",
        "instagram": "replies_ig",
        "youtube": "replies_yt",
    }
    sheet = sheet_map.get(platform)
    if not sheet:
        raise ValueError(f"Plataforma no soportada: {platform}")
    return pd.read_excel(excel_path, sheet_name=sheet)


def build_out_paths(platform: str):
    """Return (out_dir, out_json, out_ndjson, out_timing, out_csv)."""
    out_dir = os.path.join("out", "argentina", platform)
    os.makedirs(out_dir, exist_ok=True)

    suffix_map = {"twitter": "tw", "instagram": "ig", "youtube": "yt"}
    suffix = suffix_map.get(platform)
    if not suffix:
        raise ValueError(f"Plataforma no soportada para outputs: {platform}")
    out_json = os.path.join(out_dir, f"replies_llm_{suffix}.json")
    out_ndjson = os.path.join(out_dir, f"replies_llm_{suffix}.ndjson")
    out_timing = os.path.join(out_dir, f"replies_llm_{suffix}_timing.json")
    out_csv = os.path.join(out_dir, f"replies_with_labels_{suffix}.csv")

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

def make_prompt(batch):
    # batch is list of dicts: {"id":..., "text":...}
    categories_desc = json.dumps(SENTIMIENTO_DICT, ensure_ascii=False, indent=2)
    items = "\n\n".join([f"ID: {b['id']}\nTEXTO: {b['text']}" for b in batch])
    prompt = (
        f"Eres un experto en análisis de discurso y violencia de género.\n"
        "Clasifica cada texto en una o más categorías del diccionario por similitud semántica, no por coincidencia exacta.\n"
        "Devuelve únicamente un objeto JSON donde cada clave sea el ID del reply y su valor sea un objeto con: "
        "categorías_detectadas (lista) y confianza (0-1).\n\n"
        "CATEGORÍAS:\n"
        f"{categories_desc}\n\n"
        "TEXTOS A CLASIFICAR:\n"
        f"{items}\n\n"
        "RESPONDE SOLO CON JSON. EJEMPLO DE SALIDA:\n"
        '{"reply_1": {"categorías_detectadas": ["Menosprecio"], "confianza": 0.85}}'
    )
    return prompt

def parse_json_from_text(text):
    """Parse a JSON object from a model response.

    Handles common failure modes:
    - code fences ```json ... ```
    - leading/trailing commentary
    """
    if text is None:
        raise ValueError("Empty model response")

    text = text.strip()

    # Strip Markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first fence line
        if lines:
            lines = lines[1:]
        # drop last fence line if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct JSON
    try:
        return json.loads(text)
    except Exception:
        pass

    # Fallback: extract the outermost JSON object (first '{' to last '}')
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1].strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass

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
                    processed.update([str(k) for k in obj.keys()])
            except Exception:
                # ignore malformed lines
                continue
    return processed

def classify_batches(df, out_file_nd: str, out_file_timing: str, batch_size=80, model="gpt-4o-mini"):
    outputs = {}
    batch = []
    batch_times = []
    total_texts = len(df)
    total_batches = math.ceil(total_texts / batch_size)
    processed_batches = 0

    # Resume support: if NDJSON exists, skip already-processed ids to avoid re-paying.
    processed_ids = load_processed_ids_from_ndjson(out_file_nd)
    if processed_ids:
        print(f"Resume: detectados {len(processed_ids)} IDs ya procesados en {out_file_nd}. Se van a saltear.")

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
                # transient API errors
                print(f"Error llamando al modelo (intento {a}/{attempts}): {e}")
                time.sleep(1.5 * a)
        return last_content

    def process_batch_with_fallback(batch_items, batch_label: int):
        """Try to classify a batch. If model returns bad JSON, split batch to isolate bad items.

        Never raises on parse failures; returns a dict mapping ids to result objects.
        """

        def try_once(items, label_suffix: str = ""):
            prompt = make_prompt(items)
            content = call_model(prompt, attempts=3)
            if not content:
                raise ValueError("Empty model response")
            try:
                return parse_json_from_text(content)
            except Exception:
                # Retry once with a stricter reminder appended
                retry_prompt = prompt + "\n\nIMPORTANTE: Responde ÚNICAMENTE con un objeto JSON válido. Sin texto extra."
                content2 = call_model(retry_prompt, attempts=2)
                if not content2:
                    raise ValueError("Empty model response (retry)")
                return parse_json_from_text(content2)

        results_all = {}

        # Worklist for iterative splitting
        stack = [(batch_items, f"{batch_label}")]
        while stack:
            items, label = stack.pop()
            try:
                j = try_once(items)
                if isinstance(j, dict):
                    results_all.update(j)
                else:
                    raise ValueError("Parsed JSON is not a dict")
            except Exception as e:
                debug_path = os.path.join(os.path.dirname(out_file_nd), f"debug_bad_json_batch_{label}.txt")
                try:
                    # best-effort: save the prompt inputs (ids/text) to debug
                    with open(debug_path, "w", encoding="utf-8") as dfh:
                        dfh.write("\n\n".join([f"ID: {x['id']}\nTEXTO: {x['text']}" for x in items]))
                except Exception:
                    pass

                if len(items) > 1:
                    mid = len(items) // 2
                    left = items[:mid]
                    right = items[mid:]
                    # split further to isolate bad items
                    stack.append((right, f"{label}b"))
                    stack.append((left, f"{label}a"))
                    print(f"WARN: batch {label} devolvió JSON inválido ({e}). Dividiendo en {len(left)} y {len(right)}. Debug: {debug_path}")
                else:
                    # single item still failing -> record default and continue
                    bad_id = str(items[0].get("id"))
                    results_all[bad_id] = {
                        "categorías_detectadas": [],
                        "confianza": 0.0,
                        "error": "bad_json",
                    }
                    print(f"WARN: item {bad_id} no pudo parsearse como JSON. Se marca vacío y se continúa. Debug: {debug_path}")

        return results_all

    for idx, row in df.iterrows():
        rid = get_reply_id(row, idx)
        if rid in processed_ids:
            continue
        # pick best text field across platforms
        text = None
        for tc in ("text", "textDisplay", "textOriginal", "comment", "message", "body"):
            if tc in row.index and not pd.isna(row[tc]):
                text = row[tc]
                break
        if text is None:
            text = row.values[0]
        batch.append({"id": rid, "text": str(text)})
        if len(batch) >= batch_size:
            prompt = make_prompt(batch)
            processed_batches += 1
            print(f"Enviando lote de {len(batch)} textos al modelo... (batch {processed_batches}/{total_batches})")
            t0 = time.time()
            j = process_batch_with_fallback(batch, processed_batches)
            t1 = time.time()
            batch_time = t1 - t0
            batch_times.append(batch_time)
            outputs.update(j)
            try:
                processed_ids.update([str(k) for k in j.keys()])
            except Exception:
                pass
            # save intermediate batch results as NDJSON (one JSON object per line)
            try:
                with open(out_file_nd, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(j, ensure_ascii=False) + "\n")
                print(f"Resultados intermedios guardados en: {out_file_nd}")
            except Exception as e:
                print("No se pudo guardar resultados intermedios:", e)

            # estimate remaining time
            avg = sum(batch_times) / len(batch_times)
            remaining_batches = max(0, total_batches - processed_batches)
            est_remaining = remaining_batches * avg
            est_total = sum(batch_times) + remaining_batches * avg
            print(f"Tiempo lote: {batch_time:.2f}s | Promedio: {avg:.2f}s | Lotes restantes: {remaining_batches} | Est. resto: {est_remaining:.1f}s | Est. total: {est_total:.1f}s")

            batch = []
            time.sleep(0.3)

    # last partial batch
    if batch:
        processed_batches += 1
        prompt = make_prompt(batch)
        print(f"Enviando lote final de {len(batch)} textos al modelo... (batch {processed_batches}/{total_batches})")
        t0 = time.time()
        j = process_batch_with_fallback(batch, processed_batches)
        t1 = time.time()
        batch_time = t1 - t0
        batch_times.append(batch_time)
        outputs.update(j)
        try:
            processed_ids.update([str(k) for k in j.keys()])
        except Exception:
            pass
        # save last batch intermediate results
        try:
            with open(out_file_nd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(j, ensure_ascii=False) + "\n")
            print(f"Resultados intermedios guardados en: {out_file_nd}")
        except Exception as e:
            print("No se pudo guardar resultados intermedios:", e)

        # final timing estimate
        avg = sum(batch_times) / len(batch_times)
        est_total = sum(batch_times)
        print(f"Último lote tiempo: {batch_time:.2f}s | Promedio: {avg:.2f}s | Lotes procesados: {processed_batches}/{total_batches} | Tiempo total estimado: {est_total:.1f}s")

    # save timing metadata
    try:
        timing = {
            "total_texts": total_texts,
            "batch_size": batch_size,
            "total_batches": total_batches,
            "processed_batches": processed_batches,
            "per_batch_seconds": batch_times,
            "average_seconds": sum(batch_times) / len(batch_times) if batch_times else 0.0,
            "total_seconds": sum(batch_times),
        }
        with open(out_file_timing, "w", encoding="utf-8") as tf:
            json.dump(timing, tf, ensure_ascii=False, indent=2)
        print(f"Timing guardado en: {out_file_timing}")
    except Exception as e:
        print("No se pudo guardar timing:", e)

    return outputs

if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY no configurada. Exporta la variable de entorno e intenta de nuevo.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Clasifica replies por plataforma (twitter/instagram/youtube) y genera CSV con etiquetas.")
    parser.add_argument(
        "--excel",
        default="/Users/xaviergonzalez/Downloads/deliveries_proyecto_multitudes_2026-02-03_argentina.xlsx",
        help="Ruta al archivo Excel de deliveries",
    )
    parser.add_argument(
        "--platform",
        choices=["twitter", "instagram", "youtube"],
        default="twitter",
        help="Plataforma a procesar (no pisa outputs de la otra)",
    )
    parser.add_argument(
        "--run-llm",
        action="store_true",
        help="Ejecuta la clasificación con el modelo (costo $$). Por defecto NO se llama al LLM.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Permite sobrescribir outputs existentes (replies_llm.json / ndjson / timing).",
    )
    args = parser.parse_args()

    df = load_replies_sheet(args.excel, args.platform)
    out_dir, out_json, out_ndjson, out_timing, out_csv = build_out_paths(args.platform)

    # By default we do NOT call the LLM. Use --run-llm to generate results (cost $$).
    if args.run_llm:
        # prevent accidental overwrite unless explicitly allowed
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
        )
        # Save full JSON output
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print(f"Resultados guardados en: {out_json}")

    # Load existing LLM results and append category labels to dataframe
    llm_results_path = out_json
    if not os.path.exists(llm_results_path):
        print(
            f"No se encontró el archivo de resultados LLM en: {llm_results_path}\n"
            "Opciones:\n"
            "1) Si YA generaste el JSON en otro lugar, copiá/mové el archivo a esa ruta.\n"
            "2) Si querés generarlo ahora, ejecutá con: --run-llm (esto cuesta $$).\n"
            "   Ej: python src/data_analysis/sentimiento.py --platform instagram --run-llm\n"
            "       python src/data_analysis/sentimiento.py --platform youtube --run-llm\n"
        )
        sys.exit(1)

    with open(llm_results_path, "r", encoding="utf-8") as fh:
        llm_results = json.load(fh)

    # Define the six main categories (in this order)
    cats = [
        "Menosprecio",
        "Cuerpo y sexualidad",
        "Roles y género",
        "Amenazas",
        "Acoso",
        "Desprestigio",
    ]

    # Prepare new columns initialized to 0
    for c in cats:
        df[c] = 0

    # column to store the id used to lookup in llm_results for validation
    df["classified_reply_id"] = None

    # Helper to extract detected categories from LLM value
    def extract_detected(value):
        if isinstance(value, dict):
            for k in ("categorías_detectadas", "categorias_detectadas", "categories", "categorias"):
                if k in value:
                    return value[k]
            # maybe the dict is {id: {...}} style; try flatten
            # if value looks like a list/dict mapping, return empty
            return []
        elif isinstance(value, list):
            return value
        return []

    # Iterate element-wise assuming same order/length
    for idx, row in df.iterrows():
        rid = get_reply_id(row, idx)
        df.at[idx, "classified_reply_id"] = rid

        # lookup in llm_results; try str and int forms
        entry = None
        if rid in llm_results:
            entry = llm_results[rid]
        elif str(rid) in llm_results:
            entry = llm_results[str(rid)]
        else:
            # fallback: sometimes keys are plain indices like "row_0"
            fallback_key = f"row_{idx}"
            entry = llm_results.get(fallback_key)

        detected = extract_detected(entry) if entry is not None else []
        # normalize detected entries
        detected_norm = set([str(x).strip().lower() for x in detected])

        for c in cats:
            if c.lower() in detected_norm:
                df.at[idx, c] = 1

    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"Archivo con etiquetas guardado en: {out_csv}")
