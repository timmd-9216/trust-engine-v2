#!/usr/bin/env python3
"""
Script directo para obtener replies de un post usando Information Tracer API.

Este script llama directamente a la API de Information Tracer sin pasar por Firestore
ni los endpoints del servicio. Útil para testing y recupero manual de replies.

Ejemplos:
    # Obtener replies de un post de Instagram
    poetry run python scripts/fetch_post_replies_direct.py \
        --post-id 3777361292689288399 \
        --platform instagram

    # Obtener más replies (hasta el límite de la plataforma)
    poetry run python scripts/fetch_post_replies_direct.py \
        --post-id 3777361292689288399 \
        --platform instagram \
        --max-replies 100

    # Guardar resultados en archivo JSON
    poetry run python scripts/fetch_post_replies_direct.py \
        --post-id 3777361292689288399 \
        --platform instagram \
        --output results.json

    # Ordenar por engagement en lugar de tiempo
    poetry run python scripts/fetch_post_replies_direct.py \
        --post-id 3777361292689288399 \
        --platform instagram \
        --sort-by engagement
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    from trust_api.scrapping_tools.information_tracer import get_post_replies
except ImportError as e:
    missing = "dotenv" if "dotenv" in str(e) else "trust_api"
    if missing == "dotenv":
        print("Error: python-dotenv is not installed.")
        print("Install it with: poetry add python-dotenv")
    else:
        print("Error: trust_api module not found.")
        print(
            "Make sure you're running from the project root: poetry run python scripts/fetch_post_replies_direct.py"
        )
    sys.exit(1)

# Load environment variables from .env file in project root
# Find project root (parent of scripts directory)
script_dir = Path(__file__).parent
project_root = script_dir.parent
env_path = project_root / ".env"

# Load .env file explicitly from project root
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    # Fallback to default load_dotenv() behavior
    load_dotenv()


def main() -> int:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Obtener replies de un post usando Information Tracer API directamente",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Obtener replies de Instagram (default: 100 replies, orden por tiempo)
  poetry run python scripts/fetch_post_replies_direct.py \\
      --post-id 3777361292689288399 \\
      --platform instagram

  # Especificar máximo de replies
  poetry run python scripts/fetch_post_replies_direct.py \\
      --post-id 3777361292689288399 \\
      --platform instagram \\
      --max-replies 50

  # Guardar en archivo JSON
  poetry run python scripts/fetch_post_replies_direct.py \\
      --post-id 3777361292689288399 \\
      --platform instagram \\
      --output results.json

  # Ordenar por engagement
  poetry run python scripts/fetch_post_replies_direct.py \\
      --post-id 3777361292689288399 \\
      --platform instagram \\
      --sort-by engagement

Límites de plataforma:
  - Twitter: hasta 10000 replies
  - Instagram: hasta 100 replies
  - Facebook: hasta 100 replies
  - Reddit: hasta 500 replies
  - YouTube: hasta 500 replies
  - Threads: hasta 200 replies
        """,
    )

    parser.add_argument(
        "--post-id",
        type=str,
        required=True,
        help="ID del post del cual obtener replies",
    )
    parser.add_argument(
        "--platform",
        type=str,
        required=True,
        choices=["twitter", "instagram", "facebook", "reddit", "youtube", "threads"],
        help="Plataforma donde se encuentra el post (twitter, instagram, facebook, etc.)",
    )
    parser.add_argument(
        "--max-replies",
        type=int,
        default=100,
        help="Número máximo de replies a obtener (default: 100). Límites por plataforma aplican.",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        choices=["time", "engagement"],
        default="time",
        help="Orden de los replies: 'time' (cronológico) o 'engagement' (interacción) (default: time)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Archivo JSON donde guardar los resultados (opcional). Si no se especifica, imprime en stdout.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key de Information Tracer (opcional). Por defecto usa INFORMATION_TRACER_API_KEY del .env",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Mostrar información detallada del progreso",
    )

    args = parser.parse_args()

    # Get API key from .env or argument
    api_key = args.api_key or os.getenv("INFORMATION_TRACER_API_KEY")
    if not api_key:
        env_file = project_root / ".env"
        print(
            "Error: INFORMATION_TRACER_API_KEY no está configurada.",
            file=sys.stderr,
        )
        print(
            f"Opción 1: Agrega INFORMATION_TRACER_API_KEY=tu-key al archivo .env en {env_file}",
            file=sys.stderr,
        )
        print(
            "Opción 2: Usa --api-key tu-key como argumento",
            file=sys.stderr,
        )
        if not env_file.exists():
            print(
                f"\nNota: El archivo .env no existe en {env_file}",
                file=sys.stderr,
            )
            print(
                "Crea el archivo .env en la raíz del proyecto con:",
                file=sys.stderr,
            )
            print(
                "  INFORMATION_TRACER_API_KEY=tu-api-key-aqui",
                file=sys.stderr,
            )
        return 1

    try:
        if args.verbose:
            print(f"Post ID: {args.post_id}", file=sys.stderr)
            print(f"Platform: {args.platform}", file=sys.stderr)
            print(f"Max replies: {args.max_replies}", file=sys.stderr)
            print(f"Sort by: {args.sort_by}", file=sys.stderr)
            print(f"API key: {'✓ configured' if api_key else '✗ missing'}", file=sys.stderr)
            print("Submitting job to Information Tracer...", file=sys.stderr)

        # Call Information Tracer API
        result = get_post_replies(
            post_id=args.post_id,
            platform=args.platform.lower(),  # type: ignore
            max_post=args.max_replies,
            token=api_key,
            sort_by=args.sort_by,  # type: ignore
        )

        job_id = result.get("job_id")
        data = result.get("data", [])

        # Count replies
        reply_count = len(data) if isinstance(data, list) else 1

        if args.verbose:
            print(f"Job ID: {job_id}", file=sys.stderr)
            print(f"Replies retrieved: {reply_count}", file=sys.stderr)

        # Prepare output
        output_data: dict[str, Any] = {
            "post_id": args.post_id,
            "platform": args.platform.lower(),
            "job_id": job_id,
            "reply_count": reply_count,
            "max_replies_requested": args.max_replies,
            "sort_by": args.sort_by,
            "data": data,
        }

        # Save or print results
        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
            print(f"Results saved to: {output_path}", file=sys.stderr)
            print(f"Job ID: {job_id}", file=sys.stderr)
            print(f"Replies retrieved: {reply_count}", file=sys.stderr)
        else:
            # Print JSON to stdout
            print(json.dumps(output_data, ensure_ascii=False, indent=2, default=str))

        return 0

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error inesperado: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
