#!/usr/bin/env python3
"""
Script para recuperar los resultados de un job de Information Tracer usando su job_id.

Permite recuperar los datos de un job que ya fue procesado, verificando primero
su estado si es necesario.

Ejemplos:
    # Recuperar resultados de un job (auto-detecta plataforma si está en Firestore)
    poetry run python scripts/get_job_results.py \
        --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0

    # Especificar plataforma directamente
    poetry run python scripts/get_job_results.py \
        --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0 \
        --platform instagram

    # Verificar estado antes de recuperar
    poetry run python scripts/get_job_results.py \
        --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0 \
        --platform instagram \
        --check-status

    # Guardar resultados en archivo JSON
    poetry run python scripts/get_job_results.py \
        --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0 \
        --platform instagram \
        --output results.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    from trust_api.scrapping_tools.information_tracer import (
        check_status,
        get_result,
    )
except ImportError as e:
    missing = "dotenv" if "dotenv" in str(e) else "trust_api"
    if missing == "dotenv":
        print("Error: python-dotenv is not installed.")
        print("Install it with: poetry add python-dotenv")
    else:
        print("Error: trust_api module not found.")
        print(
            "Make sure you're running from the project root: poetry run python scripts/get_job_results.py"
        )
    sys.exit(1)

# Load environment variables from .env file in project root
script_dir = Path(__file__).parent
project_root = script_dir.parent
env_path = project_root / ".env"

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()


def get_platform_from_firestore(job_id: str) -> str | None:
    """Intenta obtener la plataforma desde Firestore usando el job_id."""
    try:
        from google.cloud import firestore

        client = firestore.Client()
        jobs = client.collection("pending_jobs").where("job_id", "==", job_id).limit(1).stream()

        for job in jobs:
            job_data = job.to_dict()
            platform = job_data.get("platform")
            if platform:
                return platform
    except Exception:
        # Si no se puede acceder a Firestore, retorna None
        pass
    return None


def main() -> int:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Recuperar resultados de un job de Information Tracer usando job_id",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Recuperar resultados (auto-detecta plataforma desde Firestore si está disponible)
  poetry run python scripts/get_job_results.py \\
      --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0

  # Especificar plataforma directamente
  poetry run python scripts/get_job_results.py \\
      --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0 \\
      --platform instagram

  # Verificar estado antes de recuperar
  poetry run python scripts/get_job_results.py \\
      --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0 \\
      --platform instagram \\
      --check-status

  # Guardar en archivo JSON
  poetry run python scripts/get_job_results.py \\
      --job-id 415c974a023edad465f48ca6ccd2209eccc0838981f217767338826f0d0272b0 \\
      --platform instagram \\
      --output results.json
        """,
    )

    parser.add_argument(
        "--job-id",
        type=str,
        required=True,
        help="ID del job (id_hash256) del cual recuperar resultados",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        choices=["twitter", "instagram", "facebook", "reddit", "youtube", "threads"],
        help="Plataforma del job (opcional, intenta auto-detectarlo desde Firestore si no se especifica)",
    )
    parser.add_argument(
        "--check-status",
        action="store_true",
        help="Verificar el estado del job antes de recuperar resultados",
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

    # Get API key
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
        return 1

    # Get platform
    platform = args.platform
    if not platform:
        if args.verbose:
            print(
                "Platform no especificada, intentando detectar desde Firestore...", file=sys.stderr
            )
        platform = get_platform_from_firestore(args.job_id)
        if platform:
            if args.verbose:
                print(f"✓ Platform detectada: {platform}", file=sys.stderr)
        else:
            print(
                "Error: Platform no especificada y no se pudo detectar desde Firestore.",
                file=sys.stderr,
            )
            print(
                "Usa --platform para especificar la plataforma (twitter, instagram, facebook, etc.)",
                file=sys.stderr,
            )
            return 1

    try:
        if args.verbose:
            print(f"Job ID: {args.job_id}", file=sys.stderr)
            print(f"Platform: {platform}", file=sys.stderr)

        # Check status if requested
        if args.check_status:
            if args.verbose:
                print("Verificando estado del job...", file=sys.stderr)
            status = check_status(args.job_id, api_key)
            print(f"Estado del job: {status}", file=sys.stderr)
            if status != "finished":
                print(
                    f"Advertencia: El job está en estado '{status}', los resultados pueden no estar disponibles.",
                    file=sys.stderr,
                )
                if status == "timeout":
                    print(
                        "El job puede no haber terminado aún. Intenta recuperar los resultados de todas formas.",
                        file=sys.stderr,
                    )
                elif status == "failed":
                    print(
                        "El job falló. Los resultados pueden no estar disponibles.",
                        file=sys.stderr,
                    )

        # Get results
        if args.verbose:
            print("Recuperando resultados...", file=sys.stderr)

        result = get_result(args.job_id, api_key, platform.lower())  # type: ignore

        if result is None:
            print("Error: No se pudieron recuperar los resultados del job.", file=sys.stderr)
            return 1

        # Count results
        reply_count = len(result) if isinstance(result, list) else 1

        if args.verbose:
            print(f"✓ Resultados recuperados: {reply_count} items", file=sys.stderr)

        # Prepare output
        output_data: dict[str, Any] = {
            "job_id": args.job_id,
            "platform": platform.lower(),
            "reply_count": reply_count,
            "data": result,
        }

        # Save or print results
        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
            print(f"Resultados guardados en: {output_path}", file=sys.stderr)
            print(f"Items recuperados: {reply_count}", file=sys.stderr)
        else:
            # Print JSON to stdout
            print(json.dumps(output_data, ensure_ascii=False, indent=2, default=str))

        return 0

    except Exception as e:
        print(f"Error inesperado: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
