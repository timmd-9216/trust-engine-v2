# Deploy de scrapping-tools en Vercel

Este documento describe cómo desplegar el servicio `scrapping_tools`
(`src/trust_api/scrapping_tools/`) en **Vercel**, con **Neon Postgres** como base
de datos (reemplaza Firestore) y **Vercel Blob** como almacenamiento de archivos
(reemplaza GCS). Los demás servicios del repo (`trust_api/main.py`, `nlp/`,
`vector_store/`) no se incluyen en el bundle de Vercel.

## Mapa de equivalencias GCP → Vercel

| GCP (antes)                        | Vercel (ahora)                                    |
|------------------------------------|---------------------------------------------------|
| Cloud Run (servicio HTTP)          | Python Function (`app.py`, entrypoint `app:app`)  |
| Firestore (`posts`, `pending_jobs`)| Neon Postgres (tablas `posts`, `jobs`)            |
| GCS bucket (`raw/`, `logs/`, `marts/`) | Vercel Blob store (mismos pathnames)          |
| Cloud Scheduler (POST por cron)    | Vercel Cron (GET a `/cron/*`, `Authorization: Bearer $CRON_SECRET`) |
| `GCS_BUCKET_NAME`                  | `BLOB_READ_WRITE_TOKEN`                           |
| `FIRESTORE_*`, `GCP_PROJECT_ID`    | `DATABASE_URL`                                    |

Los URIs que antes eran `gs://bucket/path` ahora se reportan como `blob://path`.

## 1. Crear el proyecto en Vercel

1. En el dashboard de Vercel: **Add New → Project**, importar este repo.
2. Framework preset: **Other** (no hay build; Vercel detecta `app.py` como
   Python Function gracias a `[tool.vercel] entrypoint = "app:app"` en
   `pyproject.toml`).
3. Las dependencias se instalan desde `[project] dependencies` del
   `pyproject.toml` (via `uv`). Los extras `nlp`, `vector` y `gcp` **no** se
   instalan en Vercel.

## 2. Integrar Neon Postgres

1. En el proyecto: **Storage → Marketplace → Neon** (o `vercel integration add`).
2. Crear/conectar la base de datos. La integración expone `DATABASE_URL`
   (pooled connection string) al proyecto automáticamente.
3. Aplicar las migraciones:

   ```bash
   export DATABASE_URL="postgresql://...neon.tech/dbname?sslmode=require"
   ./scripts/vercel/apply_migrations.sh
   ```

   Esto crea las tablas `posts` y `jobs` (`migrations/001_init.sql`, idempotente).

## 3. Integrar Vercel Blob

1. **Storage → Create Database → Blob** (access **public**).
2. Conectar el store al proyecto: esto expone `BLOB_READ_WRITE_TOKEN`.
   La API espera tokens del formato `vercel_blob_rw_{storeId}_{secret}`.

## 4. Variables de entorno

Configurar en **Settings → Environment Variables** (ver `.env.example`):

| Variable              | Requerida | Descripción                                    |
|-----------------------|-----------|------------------------------------------------|
| `DATABASE_URL`        | sí        | Connection string de Neon (la setea la integración) |
| `BLOB_READ_WRITE_TOKEN` | sí      | Token del Blob store                           |
| `INFORMATION_TRACER_API_KEY` | sí | API key del servicio externo                   |
| `CRON_SECRET`         | sí        | Secret para autenticar los crons (siempre requerido en Vercel) |
| `API_KEY`             | opcional  | Si se setea, los endpoints exigen `X-API-Key`  |
| `CRON_MAX_POSTS`      | opcional  | Posts por corrida de cron (default 10)         |
| `CRON_MAX_JOBS`       | opcional  | Jobs por corrida de cron (default 20)          |
| `POSTS_TABLE` / `JOBS_TABLE` | opcional | Nombres de tabla (defaults `posts`/`jobs`) |
| `ENABLE_JOB_LOG_REFERENCES` | opcional | Guardar referencias a logs en los jobs |

## 5. Migración de datos desde GCP

Con el entorno local autenticado en GCP (`gcloud auth application-default login`)
y los extras `gcp` instalados (`poetry install --extras "gcp"`):

```bash
# Firestore -> Neon (preserva los document IDs en jobs.post_doc_id)
DATABASE_URL=... python scripts/vercel/migrate_firestore_to_neon.py \
    --project <gcp-project> --database socialnetworks

# GCS -> Vercel Blob (mismo pathname; salta los que ya existen)
BLOB_READ_WRITE_TOKEN=... python scripts/vercel/migrate_gcs_to_blob.py \
    --bucket <bucket> --prefix raw
```

Ambos scripts aceptan `--dry-run` y `--limit` (Firestore).

## 6. Crons

`vercel.json` define los mismos schedules que Cloud Scheduler:

| Cron (UTC)      | Path                    | Equivale a                                   |
|-----------------|-------------------------|----------------------------------------------|
| `0,30 * * * *`  | `/cron/process-posts`   | `POST /process-posts?max_posts_to_process=10`|
| `15,45 * * * *` | `/cron/process-jobs`    | `POST /process-jobs?max_jobs=...`            |
| `0 7 * * *`     | `/cron/json-to-parquet` | `POST /json-to-parquet?skip_timestamp_filter=false` |

Vercel hace un **GET** al path con header `Authorization: Bearer $CRON_SECRET`;
las rutas devuelven 401 si el secret no coincide (o no está configurado).

Para verificar: **Project → Crons** en el dashboard, o manualmente:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" https://<proyecto>.vercel.app/cron/process-jobs
```

## 7. Auth de endpoints

- `/`, `/health`, `/dashboard` y `/cron/*` son públicos (los crons usan `CRON_SECRET`).
- Si `API_KEY` está configurada, el resto de endpoints exige header `X-API-Key`.
- Si `API_KEY` está vacía, no se exige nada (útil en dev local).
- El dashboard (`/dashboard`) tiene un campo para ingresar la API key; se guarda
  en `localStorage` y se envía como `X-API-Key` en todos los fetches.

## 8. Límites conocidos

- `maxDuration: 300` (5 min) requiere **plan Pro**; en Hobby el máximo es 60 s.
- En **Hobby**, los crons solo pueden correr **1 vez por día** (los schedules
  `0,30` y `15,45` por hora requieren Pro).
- Tamaño máximo del bundle de la función: 500 MB (los excludes de
  `vercel.json`/`.vercelignore` sacan stanza/torch/chromadb del paquete).

## 9. Desarrollo local

```bash
poetry install --with dev --extras "nlp vector gcp"
export DATABASE_URL=postgresql://... BLOB_READ_WRITE_TOKEN=...
uvicorn trust_api.scrapping_tools.main:app --app-dir src --reload
```
