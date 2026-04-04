import argparse
import csv
import json
import os
from typing import Any

from script_processing.sentiment_analyzer import (
    OllamaChatProvider,
    OpenRouterChatProvider,
    SentimentAnalyzer,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze tweet texts and classify sentiment using a local (Ollama) or remote (Kimi via OpenRouter) model.",
    )
    parser.add_argument("--input", required=True, help="Path to input CSV or JSON file")
    parser.add_argument(
        "--output",
        default="output_sentiment.csv",
        help="Path to output CSV (default: output_sentiment.csv)",
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
            "Model name. For ollama: e.g., gemma3 or gemma4. "
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
        help="Optional column/key used as id; if set, preserved in output.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of rows to process",
    )

    args = parser.parse_args()

    provider = _build_provider(
        provider=args.provider,
        model=args.model,
        ollama_url=args.ollama_url,
    )
    analyzer = SentimentAnalyzer(provider=provider)

    rows = _read_input(args.input)

    out_rows: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if args.limit is not None and i >= args.limit:
            break

        text = _row_text(row, args.text_column)
        result = analyzer.analyze(text)

        out_row = dict(row)
        out_row["sentiment"] = result.sentiment
        out_row["confidence"] = result.confidence
        out_rows.append(out_row)

    _write_csv(args.output, out_rows)
    return 0


def _build_provider(*, provider: str, model: str | None, ollama_url: str):
    if provider == "ollama":
        return OllamaChatProvider(
            base_url=ollama_url,
            model=model or "gemma3",
        )
    if provider == "openrouter":
        return OpenRouterChatProvider(
            model=model or "moonshotai/kimi-k2:free",
        )
    raise ValueError(f"Unknown provider: {provider}")


def _read_input(path: str) -> list[dict[str, Any]]:
    path_lower = path.lower()
    if path_lower.endswith(".csv"):
        return _read_csv(path)
    if path_lower.endswith(".json"):
        return _read_json(path)
    raise ValueError("Input must be a .csv or .json file")


def _read_csv(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def _read_json(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)

    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        if isinstance(obj.get("data"), list):
            return [x for x in obj["data"] if isinstance(x, dict)]
        return [obj]
    raise ValueError("JSON must be a list of objects or an object")


def _row_text(row: dict[str, Any], text_column: str) -> str:
    if text_column in row and row.get(text_column) is not None:
        return str(row.get(text_column) or "").strip()
    if row.get("text") is not None:
        return str(row.get("text") or "").strip()
    return ""


def _write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        # Write header anyway for consistency
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("sentiment,confidence\n")
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


if __name__ == "__main__":
    raise SystemExit(main())
