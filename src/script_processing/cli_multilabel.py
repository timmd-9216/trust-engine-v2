"""
CLI for multi-label sentiment & harassment classification using Ollama or OpenRouter.

Usage examples:

  # Ollama (local)
  poetry run python -m script_processing.cli_multilabel \
      --input tweets.csv --output out_multilabel.csv --provider ollama --model gemma3:4b

  # OpenRouter (Kimi)
  export OPENROUTER_API_KEY=...
  poetry run python -m script_processing.cli_multilabel \
      --input tweets.csv --output out_multilabel.csv --provider openrouter
"""

import argparse
import csv
import json
import os
import time
from typing import Any

from script_processing.multilabel_analyzer import (
    EMPTY_LABELS,
    LABEL_KEYS,
    classify_batch,
    normalize_entry,
)
from script_processing.sentiment_analyzer import (
    OllamaChatProvider,
    OpenRouterChatProvider,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Multi-label harassment & sentiment classifier. "
            "Uses Ollama (local) or OpenRouter (Kimi) to classify tweets/comments "
            "into 6 harassment categories + sentiment."
        ),
    )
    parser.add_argument("--input", required=True, help="Path to input CSV, JSON, or Parquet file")
    parser.add_argument(
        "--output",
        default="output_multilabel.csv",
        help="Path to output CSV (default: output_multilabel.csv)",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "openrouter"],
        default="ollama",
        help="Which provider to use: ollama (local) or openrouter (e.g., Kimi)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model name. For ollama: e.g., gemma3:4b, gemma3:12b. "
            "For openrouter: e.g., moonshotai/kimi-k2:free"
        ),
    )
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        help="Ollama base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--text-column",
        default="full_text",
        help="Column/key containing the text (default: full_text; fallback: text)",
    )
    parser.add_argument(
        "--id-column",
        default=None,
        help="Column/key used as ID. Auto-detected if not set.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Comments per batch (default: 10; lower for local models)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of rows to process",
    )
    parser.add_argument(
        "--country",
        default="Argentina",
        help="Country context for the prompt (default: Argentina)",
    )
    parser.add_argument(
        "--resume",
        default=None,
        help="Path to NDJSON file for resume support. Already-processed IDs are skipped.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds per model call (default: 120)",
    )

    args = parser.parse_args()

    # Build provider
    provider = _build_provider(
        provider=args.provider,
        model=args.model,
        ollama_url=args.ollama_url,
        timeout_s=args.timeout,
    )

    # Read input
    rows = _read_input(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    if not rows:
        print("No rows to process.")
        return 0

    print(f"Total rows: {len(rows)}")

    # Resume support
    processed_ids: set[str] = set()
    resume_path = args.resume
    if resume_path and os.path.exists(resume_path):
        processed_ids = _load_processed_ids(resume_path)
        print(f"Resume: {len(processed_ids)} IDs already processed, will skip them.")

    # Build batches, skipping already-processed
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for i, row in enumerate(rows):
        rid = _row_id(row, i, args.id_column)
        if rid in processed_ids:
            continue
        text = _row_text(row, args.text_column)
        current.append({"id": rid, "text": text.replace('"', "'")})
        if len(current) >= args.batch_size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)

    total_batches = len(batches)
    total_items = sum(len(b) for b in batches)
    print(
        f"Batches to process: {total_batches} ({total_items} items, batch_size={args.batch_size})"
    )

    # Determine output dir for debug files
    out_dir = os.path.dirname(args.output) or "."
    os.makedirs(out_dir, exist_ok=True)

    # Process batches sequentially (Ollama is single-threaded on most setups)
    all_results: dict[str, dict[str, Any]] = {}
    batch_times: list[float] = []

    for idx, batch_items in enumerate(batches):
        t0 = time.time()
        results = classify_batch(
            provider=provider,
            batch_items=batch_items,
            batch_label=str(idx + 1),
            country=args.country,
            debug_dir=out_dir,
        )
        elapsed = time.time() - t0
        batch_times.append(elapsed)
        all_results.update(results)

        # Append to NDJSON for resume
        if resume_path:
            try:
                with open(resume_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(results, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"WARN: could not write resume NDJSON: {e}")

        avg = sum(batch_times) / len(batch_times)
        remaining = total_batches - (idx + 1)
        est = remaining * avg
        print(
            f"Batch {idx + 1}/{total_batches} done ({len(results)} IDs) | "
            f"{elapsed:.1f}s | Avg: {avg:.1f}s | "
            f"Remaining: ~{est:.0f}s"
        )

    # Merge results back into rows and write CSV
    _write_output(args.output, rows, all_results, args.text_column, args.id_column)

    print(f"\nOutput saved to: {args.output}")
    if batch_times:
        print(
            f"Total time: {sum(batch_times):.1f}s | "
            f"Avg per batch: {sum(batch_times) / len(batch_times):.1f}s"
        )
    return 0


# ---- Helpers ----


def _build_provider(*, provider: str, model: str | None, ollama_url: str, timeout_s: float):
    if provider == "ollama":
        return OllamaChatProvider(
            base_url=ollama_url,
            model=model or "gemma3:4b",
            timeout_s=timeout_s,
        )
    if provider == "openrouter":
        return OpenRouterChatProvider(
            model=model or "moonshotai/kimi-k2:free",
            timeout_s=timeout_s,
        )
    raise ValueError(f"Unknown provider: {provider}")


def _read_input(path: str) -> list[dict[str, Any]]:
    ext = path.lower()
    if ext.endswith(".csv"):
        return _read_csv(path)
    if ext.endswith(".json"):
        return _read_json(path)
    if ext.endswith(".parquet"):
        return _read_parquet(path)
    raise ValueError("Input must be a .csv, .json, or .parquet file")


def _read_csv(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def _read_json(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict) and isinstance(obj.get("data"), list):
        return [x for x in obj["data"] if isinstance(x, dict)]
    if isinstance(obj, dict):
        return [obj]
    raise ValueError("JSON must be a list of objects or an object with 'data' key")


def _read_parquet(path: str) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    cols = table.column_names
    rows: list[dict[str, Any]] = []
    arrays = {c: table.column(c).to_pylist() for c in cols}
    for i in range(table.num_rows):
        rows.append({c: arrays[c][i] for c in cols})
    return rows


ID_COLUMNS = [
    "tweet_id",
    "id_str",
    "reply_id",
    "replyId",
    "id",
    "replyid",
    "comment_id",
    "commentId",
    "comment_id_str",
    "video_id",
    "videoId",
]


def _row_id(row: dict[str, Any], idx: int, id_column: str | None = None) -> str:
    if id_column and row.get(id_column) is not None:
        return str(row[id_column])
    for col in ID_COLUMNS:
        if col in row and row[col] is not None and str(row[col]).strip():
            return str(row[col])
    return f"row_{idx}"


def _row_text(row: dict[str, Any], text_column: str) -> str:
    if text_column in row and row.get(text_column) is not None:
        return str(row[text_column]).strip()
    for fallback in (
        "text",
        "full_text",
        "textDisplay",
        "textOriginal",
        "comment",
        "message",
        "body",
    ):
        if fallback in row and row.get(fallback) is not None:
            return str(row[fallback]).strip()
    return ""


def _load_processed_ids(ndjson_path: str) -> set[str]:
    ids: set[str] = set()
    with open(ndjson_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    ids.update(str(k) for k in obj.keys())
            except Exception:
                continue
    return ids


LABEL_DISPLAY = {
    "menosprecio": "Menosprecio",
    "cuerpo_y_sexualidad": "Cuerpo y sexualidad",
    "roles_y_genero": "Roles y género",
    "amenazas": "Amenazas",
    "acoso": "Acoso",
    "desprestigio": "Desprestigio",
}


def _write_output(
    path: str,
    rows: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
    text_column: str,
    id_column: str | None,
) -> None:
    """Write CSV with original columns + label columns + sentimiento + confidence."""
    if not rows:
        return

    # Determine fieldnames: original + new columns
    original_fields = list(rows[0].keys())
    extra_fields = (
        ["classified_id"]
        + [LABEL_DISPLAY[k] for k in LABEL_KEYS]
        + ["classified_sentimiento", "classified_confidence"]
    )
    fieldnames = original_fields + extra_fields

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, row in enumerate(rows):
            rid = _row_id(row, i, id_column)
            entry = results.get(rid, {})
            if not entry:
                entry = results.get(str(rid), {})
            if not entry:
                entry = results.get(f"row_{i}", {})

            if entry:
                entry = normalize_entry(entry)
            labels = entry.get("labels", EMPTY_LABELS) if entry else EMPTY_LABELS

            out_row = dict(row)
            out_row["classified_id"] = rid
            for key in LABEL_KEYS:
                out_row[LABEL_DISPLAY[key]] = 1 if labels.get(key) else 0
            out_row["classified_sentimiento"] = (
                entry.get("sentimiento", "neutro") if entry else "neutro"
            )
            out_row["classified_confidence"] = entry.get("confidence", 0.0) if entry else 0.0
            writer.writerow(out_row)


if __name__ == "__main__":
    raise SystemExit(main())
