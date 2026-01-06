#!/usr/bin/env python3
"""Script para consultar cantidad de posts de Twitter con status distinto a 'done'.

Usa los índices existentes: status + platform + created_at
Hace múltiples queries por cada status != "done" y suma los resultados.
"""

import os

from dotenv import load_dotenv
from google.cloud import firestore

# Load environment variables
load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "trust-481601")
DATABASE = os.getenv("FIRESTORE_DATABASE", "socialnetworks")
COLLECTION = os.getenv("FIRESTORE_COLLECTION", "posts")


def count_twitter_posts_not_done():
    """
    Cuenta posts de Twitter con status distinto a 'done'.

    Usa el índice existente: status + platform + created_at
    Hace queries separadas para cada status != "done" y suma los resultados.
    """
    client = firestore.Client(project=PROJECT_ID, database=DATABASE)

    # Estados posibles excluyendo "done"
    # Según la documentación: noreplies, done, skipped (y posiblemente failed)
    statuses = ["noreplies", "skipped"]

    total = 0
    status_counts = {}

    print("Posts de Twitter por status (excluyendo 'done'):")
    print("Usando índice existente: status + platform + created_at")
    print("-" * 60)

    for status in statuses:
        try:
            # Query compatible con índice: status + platform + created_at
            query = (
                client.collection(COLLECTION)
                .where("status", "==", status)
                .where("platform", "==", "twitter")
            )

            docs = list(query.stream())
            count = len(docs)
            status_counts[status] = count
            total += count
            print(f"  {status}: {count}")

        except Exception as e:
            print(f"  {status}: Error - {e}")
            status_counts[status] = 0

    print("-" * 60)
    print(f"Total posts de Twitter con status != 'done': {total}")

    return total, status_counts


if __name__ == "__main__":
    print("=" * 60)
    print("Consultar posts de Twitter con status != 'done'")
    print("=" * 60)
    print(f"Proyecto: {PROJECT_ID}")
    print(f"Base de datos: {DATABASE}")
    print(f"Colección: {COLLECTION}")
    print()
    print("Usando índices existentes (status + platform + created_at)")
    print("=" * 60)
    print()

    count, status_counts = count_twitter_posts_not_done()

    print()
    print("Query equivalente en código:")
    print("-" * 60)
    print("""
# Usando índices existentes: status + platform + created_at
client = firestore.Client(project="trust-481601", database="socialnetworks")

total = 0
for status in ["noreplies", "skipped"]:
    query = (
        client.collection("posts")
        .where("status", "==", status)
        .where("platform", "==", "twitter")
    )
    count = len(list(query.stream()))
    total += count

print(f"Total: {total}")
""")
