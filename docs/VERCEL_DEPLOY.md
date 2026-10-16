# Migración de scrapping-tools a Vercel — paso a paso

Este documento es el runbook completo para poner en producción el servicio
`scrapping_tools` (`src/trust_api/scrapping_tools/`) en **Vercel**, con
**Neon Postgres** (reemplaza Firestore) y **Vercel Blob** (reemplaza GCS).

## Estado actual (qué ya está hecho)

- Branch `feat/vercel-migration` pusheada a
  `github.com/timmd-9216/trust-engine-v2-vercel` (commit `7ef900b`).
- Código migrado: capa Postgres (`db.py`), capa Blob (`blob.py`), rutas
  `/cron/*`, auth por `X-API-Key`, `app.py` entrypoint, `vercel.json` con
  los 3 crons, `.vercelignore`, `migrations/001_init.sql`, scripts de
  migración en `scripts/vercel/`.
- Tests: 42/42 unitarios y 9/9 de integración contra Postgres en verde.
- **No hay nada deployado todavía.** Falta crear el proyecto en Vercel y
  provisionar storage (pasos 1–3).

## Mapa de equivalencias GCP → Vercel

| GCP (antes)                          | Vercel (ahora)                                                  |
|--------------------------------------|-----------------------------------------------------------------|
| Cloud Run (servicio HTTP)            | Python Function (`app.py`, entrypoint `app:app`)                |
| Firestore (`posts`, `pending_jobs`)  | Neon Postgres (tablas `posts`, `jobs`)                          |
| GCS bucket (`raw/`, `logs/`, `marts/`) | Vercel Blob store (mismos pathnames)                          |
| Cloud Scheduler (POST por cron)      | Vercel Cron (GET a `/cron/*`, `Authorization: Bearer $CRON_SECRET`) |
| `GCS_BUCKET_NAME`                    | `BLOB_READ_WRITE_TOKEN`                                         |
| `FIRESTORE_*`, `GCP_PROJECT_ID`      | `DATABASE_URL`                                                  |

Los URIs que antes eran `gs://bucket/path` ahora se reportan como `blob://path`.

## Paso 0 — Prerequisitos

- Cuenta de Vercel (plan **Pro** recomendado; ver "Límites conocidos" abajo).
- `vercel` CLI instalado y logueado: `vercel whoami` debe responder con tu
  usuario.
- Acceso a GCP (para la migración de datos):
  `gcloud auth application-default login`.
- Entorno Python del repo: `poetry install --with dev --extras "nlp vector gcp"`.

## Paso 1 — Crear el proyecto en Vercel

**Opción A (recomendada) — Dashboard, con deploys por git push:**

1. [vercel.com/new](https://vercel.com/new) → **Import Git Repository** →
   `timmd-9216/trust-engine-v2-vercel`.
2. Framework preset: **Other** (no hay build command; Vercel detecta
   `app.py` como Python Function via `[tool.vercel] entrypoint` en
   `pyproject.toml`). Root directory: `.` (raíz).
3. Deploy. Este primer deploy va a fallar en runtime hasta que existan las
   env vars (paso 4) — sirve para validar que el build instala las
   dependencias sin stanza/torch.
4. De ahora en más, cada push a la branch genera un preview deploy
   automático.

**Opción B — CLI (sin integración git):**

```bash
cd trust-engine-v2
vercel link --repo          # enlaza el repo a un proyecto nuevo/existente
vercel deploy -y --no-wait  # deploy de preview
vercel inspect <url>        # estado del build
```

## Paso 2 — Neon Postgres

1. En el proyecto: **Storage → Marketplace → Neon** → crear/conectar la DB.
   La integración setea `DATABASE_URL` sola en el proyecto.
2. Aplicar el schema (crea `posts` y `jobs`, idempotente):

   ```bash
   export DATABASE_URL="postgresql://...neon.tech/dbname?sslmode=require"
   ./scripts/vercel/apply_migrations.sh
   ```

## Paso 3 — Vercel Blob

1. **Storage → Create Database → Blob** (access **public**).
2. Conectar el store al proyecto → expone `BLOB_READ_WRITE_TOKEN`
   (formato `vercel_blob_rw_{storeId}_{secret}`).

## Paso 4 — Variables de entorno

En **Settings → Environment Variables** (o `vercel env add <NAME>` por CLI):

| Variable                  | Requerida | Descripción                                    |
|---------------------------|-----------|------------------------------------------------|
| `DATABASE_URL`            | sí        | La setea la integración de Neon                |
| `BLOB_READ_WRITE_TOKEN`   | sí        | La setea el Blob store                          |
| `INFORMATION_TRACER_API_KEY` | sí     | API key del servicio externo                    |
| `CRON_SECRET`             | sí        | String random ≥16 chars; autentica los crons    |
| `API_KEY`                 | recomendada | Si se setea, los endpoints exigen `X-API-Key` |
| `CRON_MAX_POSTS`          | opcional  | Posts por corrida de cron (default 10)          |
| `CRON_MAX_JOBS`           | opcional  | Jobs por corrida de cron (default 20)           |
| `POSTS_TABLE` / `JOBS_TABLE` | opcional | Nombres de tabla (defaults `posts`/`jobs`)     |
| `ENABLE_JOB_LOG_REFERENCES` | opcional | Guardar referencias a logs en los jobs         |

Generar los secrets: `openssl rand -hex 32`.

Después de setearlas: `vercel redeploy` o push vacío para redeployar.

## Paso 5 — Migración de datos desde GCP

Correr local con `.env` apuntando a Neon/Blob:

```bash
# Firestore -> Neon (preserva los doc IDs; jobs.post_doc_id sigue apuntando bien)
DATABASE_URL=... python scripts/vercel/migrate_firestore_to_neon.py \
    --project <gcp-project> --database socialnetworks

# GCS -> Vercel Blob (mismo pathname; salta los que ya existen)
BLOB_READ_WRITE_TOKEN=... python scripts/vercel/migrate_gcs_to_blob.py \
    --bucket <bucket> --prefix raw
```

Ambos aceptan `--dry-run`. El de Firestore también `--limit`. Son
idempotentes (upserts / skip de blobs existentes) → se pueden re-correr
durante el cutover para sincronizar el delta.

## Paso 6 — Verificar el deploy

```bash
BASE=https://<proyecto>.vercel.app

curl $BASE/health                                          # 200, público
curl $BASE/dashboard                                       # 200 HTML
curl "$BASE/jobs/count?status=pending"                     # 401 (sin key)
curl "$BASE/jobs/count?status=pending" -H "X-API-Key: $API_KEY"  # 200
```

En `/dashboard` hay un campo para la API key (se guarda en `localStorage`
y se envía como `X-API-Key`).

## Paso 7 — Crons

`vercel.json` registra automáticamente los mismos schedules que Cloud
Scheduler:

| Cron (UTC)      | Path                    | Equivale a                                        |
|-----------------|-------------------------|---------------------------------------------------|
| `0,30 * * * *`  | `/cron/process-posts`   | `POST /process-posts?max_posts_to_process=10`     |
| `15,45 * * * *` | `/cron/process-jobs`    | `POST /process-jobs?max_jobs=...`                 |
| `0 7 * * *`     | `/cron/json-to-parquet` | `POST /json-to-parquet?skip_timestamp_filter=false` |

Vercel hace GET con `Authorization: Bearer $CRON_SECRET`; sin el secret
correcto devuelve 401. Verificar en **Project → Cron Jobs**, o disparar a
mano:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" $BASE/cron/process-jobs
```

## Paso 8 — Cutover desde GCP

1. Confirmar en Vercel que `/jobs/count`, `/posts/count` y un cron manual
   devuelven números coherentes con Firestore/GCS.
2. Pausar los Cloud Scheduler jobs (no borrarlos todavía):
   `gcloud scheduler jobs pause <job> --location <region>` para los 3.
3. Re-correr los scripts del paso 5 para sincronizar el delta.
4. Monitorear logs de la función en Vercel durante 1–2 ciclos de cron.
5. Cuando Vercel esté estable: apagar el servicio Cloud Run
   (`gcloud run services update <svc> --no-traffic` o escalar a 0) y
   después borrar los Scheduler jobs.

## Rollback

Si algo falla, el sistema GCP queda intacto: reanudar los Scheduler jobs
(`gcloud scheduler jobs resume`) y volver a apuntar los llamadores al
servicio Cloud Run. La data en Vercel se descarta o se re-sincroniza a GCP
con un script inverso si hubiera escrituras nuevas.

## Límites conocidos

- `maxDuration: 300` requiere **plan Pro**; en Hobby el máximo es 60 s y
  los crons corren **máximo 1×/día** (los schedules cada 30 min no andan).
- Bundle máximo de la función: 500 MB (los excludes sacan stanza/torch/
  chromadb del paquete).
- `process-posts`/`process-jobs` procesan tandas por corrida; si una tanda
  supera el `maxDuration`, bajar `CRON_MAX_POSTS`/`CRON_MAX_JOBS`.

## Notas sobre Python GA en Vercel (oct-2026) y futuro

- Python es first-class (`pyproject.toml` + `uv`), que es lo que usa esta
  migración.
- **Container Functions** permiten deployar un `Dockerfile` con libs de
  sistema — es la vía para migrar `main`/`nlp` (Stanza/PyTorch) a Vercel
  sin reescribir con LLM, si se quiere en el futuro.
- **Vercel Daemons** (beta pública) son workers pull-based continuos:
  reemplazarían el polling cada 30 min por un loop que consuma `jobs`
  directamente de Postgres. Evaluar cuando salga de beta.
- SDK oficial de Python (`pip install vercel`) incluye Blob; `blob.py`
  usa la REST API directa con httpx (misma superficie, cero dependencias).

## Desarrollo local

```bash
poetry install --with dev --extras "nlp vector gcp"
export DATABASE_URL=postgresql://... BLOB_READ_WRITE_TOKEN=...
uvicorn trust_api.scrapping_tools.main:app --app-dir src --reload
```

Tests: `poetry run pytest tests/test_scrapping_tools.py` (unitarios,
con mocks) y `TEST_DATABASE_URL=... pytest tests/test_db_integration.py`
(contra un Postgres real).
