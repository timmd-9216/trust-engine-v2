#!/usr/bin/env python3
"""Script para verificar posts con JSON vacíos en GCS.

Busca posts en Firestore con status='done' para un candidate_id dado (o todos si no se especifica),
y verifica si el JSON correspondiente en GCS es una lista vacía.
Genera un CSV con los resultados.
"""

import csv
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from google.cloud import firestore, storage

# Load environment variables
load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "trust-481601")
DATABASE = os.getenv("FIRESTORE_DATABASE", "socialnetworks")
COLLECTION = os.getenv("FIRESTORE_COLLECTION", "posts")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")


def _get_gcs_blob_path(
    country: str,
    platform: str,
    candidate_id: str,
    post_id: str,
) -> str:
    """
    Generate the GCS blob path for a post.

    Args:
        country: Country name
        platform: Platform name
        candidate_id: Candidate ID
        post_id: Post ID (used for filename)

    Returns:
        Blob path in GCS
    """
    # Normalize path components to avoid issues with special characters
    safe_country = country.replace("/", "_").replace("\\", "_")
    safe_platform = platform.replace("/", "_").replace("\\", "_")
    safe_candidate_id = str(candidate_id).replace("/", "_").replace("\\", "_")
    safe_post_id = str(post_id).replace("/", "_").replace("\\", "_")

    layer_name = "raw"
    return f"{layer_name}/{safe_country}/{safe_platform}/{safe_candidate_id}/{safe_post_id}.json"


def verify_posts_json(candidate_id: str | None = None, output_csv: str | None = None) -> list[dict]:
    """
    Verifica posts con status='done' y verifica si los JSON en GCS están vacíos.

    Args:
        candidate_id: ID del candidato a verificar (opcional, si es None verifica todos)
        output_csv: Ruta del archivo CSV de salida (opcional)

    Returns:
        Lista de diccionarios con los resultados de la verificación
    """
    if not GCS_BUCKET_NAME:
        raise ValueError("GCS_BUCKET_NAME no está configurado en las variables de entorno")

    # Initialize clients
    firestore_client = firestore.Client(project=PROJECT_ID, database=DATABASE)
    gcs_client = storage.Client(project=PROJECT_ID)
    bucket = gcs_client.bucket(GCS_BUCKET_NAME)

    # Query Firestore for posts with status='done'
    if candidate_id:
        print(f"Buscando posts con status='done' y candidate_id='{candidate_id}'...")
        query = (
            firestore_client.collection(COLLECTION)
            .where("status", "==", "done")
            .where("candidate_id", "==", candidate_id)
        )
    else:
        print("Buscando posts con status='done' para todos los candidate_id...")
        query = firestore_client.collection(COLLECTION).where("status", "==", "done")

    posts = list(query.stream())
    print(f"Encontrados {len(posts)} posts")

    results = []
    empty_count = 0
    missing_count = 0
    error_count = 0

    for doc in posts:
        doc_data = doc.to_dict()
        post_id = doc_data.get("post_id", "")
        platform = doc_data.get("platform", "")
        country = doc_data.get("country", "")
        doc_candidate_id = doc_data.get("candidate_id", "")
        replies_count = doc_data.get("replies_count", None)

        # Get GCS blob path
        blob_path = _get_gcs_blob_path(country, platform, doc_candidate_id, post_id)
        blob = bucket.blob(blob_path)

        result = {
            "post_id": post_id,
            "platform": platform,
            "country": country,
            "candidate_id": doc_candidate_id,
            "replies_count": replies_count,
            "gcs_path": blob_path,
            "file_exists": False,
            "is_empty_list": False,
            "error": None,
        }

        try:
            if blob.exists():
                result["file_exists"] = True
                # Read and parse JSON
                content = blob.download_as_text()
                json_data = json.loads(content)

                # Check if it's an empty list
                if isinstance(json_data, list) and len(json_data) == 0:
                    result["is_empty_list"] = True
                    empty_count += 1
            else:
                result["error"] = "File not found in GCS"
                missing_count += 1
        except json.JSONDecodeError as e:
            result["error"] = f"Invalid JSON: {str(e)}"
            error_count += 1
        except Exception as e:
            result["error"] = f"Error reading file: {str(e)}"
            error_count += 1

        results.append(result)

    # Print summary
    print("\n" + "=" * 60)
    print("Resumen:")
    print(f"  Total posts verificados: {len(results)}")
    print(f"  Posts con lista vacía: {empty_count}")
    print(f"  Archivos no encontrados: {missing_count}")
    print(f"  Errores: {error_count}")
    print("=" * 60)

    # Generate CSV if requested
    if output_csv:
        print(f"\nGenerando CSV: {output_csv}")
        with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "post_id",
                "platform",
                "country",
                "candidate_id",
                "replies_count",
                "gcs_path",
                "file_exists",
                "is_empty_list",
                "error",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print(f"CSV generado exitosamente: {output_csv}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Verifica posts con JSON vacíos en GCS para un candidate_id (o todos si no se especifica)"
    )
    parser.add_argument(
        "candidate_id",
        type=str,
        nargs="?",
        default=None,
        help="ID del candidato a verificar (opcional, si no se especifica verifica todos)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Ruta del archivo CSV de salida (por defecto: candidate_id_verification_TIMESTAMP.csv o all_candidates_verification_TIMESTAMP.csv)",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="GCP Project ID (sobrescribe .env)",
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=None,
        help="GCS Bucket name (sobrescribe .env)",
    )

    args = parser.parse_args()

    # Override config if provided
    if args.project_id:
        PROJECT_ID = args.project_id
    if args.bucket:
        GCS_BUCKET_NAME = args.bucket

    if not GCS_BUCKET_NAME:
        print("Error: GCS_BUCKET_NAME no está configurado", file=sys.stderr)
        print("Configúralo en .env o usa --bucket", file=sys.stderr)
        sys.exit(1)

    # Generate default output filename if not provided
    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.candidate_id:
            args.output = f"{args.candidate_id}_verification_{timestamp}.csv"
        else:
            args.output = f"all_candidates_verification_{timestamp}.csv"

    print("=" * 60)
    print("Verificación de posts con JSON vacíos en GCS")
    print("=" * 60)
    print(f"Proyecto: {PROJECT_ID}")
    print(f"Base de datos: {DATABASE}")
    print(f"Colección: {COLLECTION}")
    print(f"Bucket GCS: {GCS_BUCKET_NAME}")
    if args.candidate_id:
        print(f"Candidate ID: {args.candidate_id}")
    else:
        print("Candidate ID: TODOS")
    print()

    try:
        results = verify_posts_json(args.candidate_id, args.output)
        print(f"\nVerificación completada. {len(results)} posts procesados.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
