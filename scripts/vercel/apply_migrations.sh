#!/usr/bin/env bash
# Apply Postgres migrations to the database pointed by DATABASE_URL (Neon).
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

psql "$DATABASE_URL" -f "${REPO_ROOT}/migrations/001_init.sql"
echo "Migrations applied."
