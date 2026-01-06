# Data Lake Architecture

Este documento describe la arquitectura del Data Lake para analytics del Trust Engine.

## Guía Paso a Paso

### Setup Inicial (Una sola vez)

#### Paso 1: Crear las tablas de BigQuery

```bash
cd terraform
terraform init
terraform apply \
  -var="project_id=trust-481601" \
  -var="region=us-east1" \
  -var="gcs_bucket=trust-prd"
```

Esto crea:
- Dataset: `trust_analytics`
- External Table: `replies` (apunta a `gs://trust-prd/processed/replies/*`)
- Vistas: `twitter_replies`, `instagram_replies`, `daily_engagement`, `candidate_summary`

### Proceso Recurrente (Cuando hay nuevos datos)

#### Paso 2: Transformar JSONs a Parquet

Transforma los JSONs originales de Information Tracer a formato Parquet optimizado.

**Opción A: Usar el endpoint del servicio (Recomendado - con optimizaciones)**

El endpoint `/json-to-parquet` del servicio `scrapping-tools` incluye optimizaciones de carga incremental:

```bash
# Usar el endpoint del servicio (optimizado con carga incremental)
curl -X POST "http://localhost:8082/json-to-parquet?country=honduras&platform=twitter"

# O desde Cloud Run (producción)
curl -X POST "https://scrapping-tools-XXXXX.run.app/json-to-parquet?country=honduras&platform=twitter"
```

**Ventajas del endpoint**:
- ✅ Carga incremental: Solo procesa JSONs nuevos (comparación de timestamps)
- ✅ No sobreescribe: Fusiona nuevos registros con existentes
- ✅ Deduplicación automática: Evita duplicados por `(source_file, tweet_id)`
- ✅ Eficiente: Reduce I/O y procesamiento en 99% en ejecuciones incrementales

Ver [JSON_TO_PARQUET_OPTIMIZATIONS.md](./JSON_TO_PARQUET_OPTIMIZATIONS.md) para detalles de las optimizaciones.

**Opción B: Usar el script standalone (carga completa)**

```bash
# Procesar todos los JSONs de un país/plataforma y subir a GCS
poetry run python scripts/json_to_parquet.py \
  --bucket trust-prd \
  --country honduras \
  --platform twitter \
  --upload

# O si ya generaste los Parquet localmente, solo subirlos:
poetry run python scripts/upload_parquet_to_gcs.py \
  --source-dir ./data/processed \
  --bucket trust-prd
```

**Nota**: El script standalone procesa todos los JSONs cada vez. Para cargas incrementales, usar el endpoint.

**Resultado**: Archivos Parquet guardados en `gs://trust-prd/processed/replies/` con estructura:
```
processed/replies/ingestion_date={date}/platform={platform}/data.parquet
```

**Nota**: El orden de particiones (`ingestion_date` primero, luego `platform`) es crítico y debe mantenerse consistente. Ver sección [Particionamiento](#particionamiento) para más detalles.

#### Paso 3: Consultar en BigQuery

Las tablas se actualizan automáticamente. No necesitas ejecutar nada más. Simplemente consulta:

```sql
-- Ver datos nuevos inmediatamente
SELECT * 
FROM `trust-481601.trust_analytics.replies`
WHERE ingestion_date = CURRENT_DATE()
LIMIT 100;
```

### Resumen del Flujo

```
1. JSONs en GCS (raw/)
   ↓
2. Ejecutar /json-to-parquet endpoint (recomendado) o json_to_parquet.py --upload
   ↓
3. Parquet en GCS (processed/replies/) - con carga incremental
   ↓
4. BigQuery External Table lee automáticamente (sin acción necesaria)
   ↓
5. Queries SQL en BigQuery
```

**Nota**: El endpoint `/json-to-parquet` es preferible para ejecuciones recurrentes porque solo procesa JSONs nuevos, mientras que el script procesa todos los JSONs cada vez.

**Nota**: El Paso 1 (crear tablas) se hace una sola vez. Los Pasos 2-3 se repiten cada vez que quieras procesar nuevos datos.

---

## Estructura del Bucket GCS

```
gs://trust-prd/
│
├── raw/                              # Capa RAW - JSONs originales
│   └── {country}/
│       └── {platform}/
│           └── {candidate_id}/
│               └── {post_id}.json    # JSON de Information Tracer
│
├── processed/                        # Capa PROCESSED - Parquet optimizado
│   └── replies/
│       └── ingestion_date=YYYY-MM-DD/
│           └── platform={twitter|instagram}/
│               └── data.parquet      # Parquet particionado
│
├── logs/                             # Logs de ejecución
│   └── YYYY-MM-DD/
│       └── HH-MM-SS.json
│
└── errors/                           # Logs de errores
    └── YYYY-MM-DD/
        └── HH-MM-SS.json
```

## Capas del Data Lake

### 1. Raw Layer (JSONs)

**Ubicación**: `gs://{bucket}/raw/{country}/{platform}/{candidate_id}/{post_id}.json`

- Datos originales de Information Tracer
- Sin transformación
- Preserva historial con `_metadata.older_version` en reintentos
- Formato: JSON

**⚠️ Estructura Requerida**: Los archivos **deben** estar organizados con `candidate_id` como subdirectorio:
- ✅ **Correcto**: `raw/honduras/instagram/hnd01monc/post123.json`
- ❌ **Incorrecto**: `raw/honduras/instagram/post123.json` (sin subdirectorio de candidato)

El script `json_to_parquet.py` automáticamente **ignora** archivos que no tengan la estructura correcta.

**Campos principales (Twitter)**:
```json
{
  "id_str": "123456789",
  "created_at": "Mon Jan 05 12:00:00 +0000 2026",
  "full_text": "Reply text...",
  "user": {
    "screen_name": "username",
    "followers_count": 1000
  },
  "favorite_count": 5,
  "retweet_count": 2,
  "reply_count": 1
}
```

### 2. Processed Layer (Parquet)

**Ubicación**: `gs://{bucket}/processed/replies/ingestion_date={date}/platform={platform}/data.parquet`

- Datos transformados y optimizados
- Schema definido y tipado
- Particionado por `ingestion_date` y `platform` (orden: ingestion_date primero)
- Formato: Parquet (compresión Snappy)

**Schema Twitter**:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `ingestion_date` | DATE | Fecha de ingesta (partición) |
| `ingestion_timestamp` | TIMESTAMP | Timestamp exacto de ingesta |
| `source_file` | STRING | Path del JSON original |
| `country` | STRING | País del candidato |
| `platform` | STRING | Plataforma (twitter/instagram) |
| `candidate_id` | STRING | ID del candidato |
| `parent_post_id` | STRING | ID del post original |
| `tweet_id` | STRING | ID del tweet/reply |
| `tweet_url` | STRING | URL del tweet |
| `created_at` | STRING | Fecha de creación del tweet |
| `full_text` | STRING | Texto completo |
| `lang` | STRING | Idioma detectado |
| `user_id` | STRING | ID del autor |
| `user_screen_name` | STRING | Username del autor |
| `user_name` | STRING | Nombre del autor |
| `user_followers_count` | INT64 | Seguidores del autor |
| `user_friends_count` | INT64 | Seguidos del autor |
| `user_verified` | BOOL | Usuario verificado |
| `reply_count` | INT64 | Cantidad de replies |
| `retweet_count` | INT64 | Cantidad de retweets |
| `quote_count` | INT64 | Cantidad de quotes |
| `favorite_count` | INT64 | Cantidad de likes |
| `is_reply` | BOOL | Es una reply |
| `is_retweet` | BOOL | Es un retweet |
| `is_quote_status` | BOOL | Es un quote tweet |
| `has_media` | BOOL | Tiene media adjunta |
| `media_count` | INT64 | Cantidad de media |
| `is_retry` | BOOL | Es un reintento |
| `retry_count` | INT64 | Número de reintento |

## Particionamiento

### Estructura de Particiones

Los datos Parquet están particionados usando **Hive Partitioning** con el siguiente orden:

```
processed/replies/ingestion_date={YYYY-MM-DD}/platform={platform}/data.parquet
```

**Orden de particiones**:
1. `ingestion_date` (primero)
2. `platform` (segundo)

**Ejemplo**:
```
gs://trust-prd/processed/replies/
├── ingestion_date=2025-12-30/
│   ├── platform=twitter/
│   │   └── data.parquet
│   └── platform=instagram/
│       └── data.parquet
└── ingestion_date=2025-12-31/
    ├── platform=twitter/
    │   └── data.parquet
    └── platform=instagram/
        └── data.parquet
```

### ¿Por qué este orden?

El orden `ingestion_date` primero, luego `platform` es **crítico** para BigQuery:

1. **Consistencia con BigQuery**: BigQuery requiere que el orden de particiones sea consistente en todos los archivos. Si detecta diferentes órdenes, falla con el error:
   ```
   Partition keys should be invariant from table creation across all partitions
   ```

2. **Eficiencia de queries temporales**: La mayoría de queries filtran por rango de fechas:
   ```sql
   WHERE ingestion_date BETWEEN '2026-01-01' AND '2026-01-31'
   ```
   Con `ingestion_date` primero, BigQuery puede hacer **partition pruning** más eficiente.

3. **Compatibilidad con Hive Partitioning**: El orden debe coincidir exactamente con la estructura de directorios en GCS.

### ¿Por qué particionar por `ingestion_date`?

1. **Eficiencia de queries**: BigQuery solo escanea las particiones necesarias
2. **Idempotencia**: Puedes reprocesar un día sin afectar otros
3. **Debugging**: Fácil identificar cuándo se ingirió un dato
4. **Incremental**: Agregar datos nuevos sin tocar históricos
5. **Costo**: Reduce bytes escaneados → menor costo

### Partición por `platform`

El campo `platform` (twitter/instagram) también particiona los datos, permitiendo:
- Queries rápidos por plataforma
- Schemas unificados (mismos nombres de campos para ambas plataformas)
- Filtrado eficiente cuando se combina con `ingestion_date`

### Importante: Orden de Particiones

⚠️ **CRÍTICO**: El orden de particiones (`ingestion_date` primero, luego `platform`) **debe ser consistente** en:
- La estructura de directorios en GCS
- La definición de la tabla externa en BigQuery
- El script `json_to_parquet.py` que genera los archivos

Si cambias el orden en un lugar, debes cambiarlo en todos los lugares. De lo contrario, BigQuery fallará al crear o consultar la tabla externa.

### Troubleshooting

Si ves el error:
```
Partition keys should be invariant from table creation across all partitions
```

**Causas posibles**:
1. Archivos Parquet con diferentes órdenes de particiones en el bucket
2. La tabla externa fue creada con un orden diferente al de los archivos actuales
3. Mezcla de archivos antiguos y nuevos con diferentes estructuras

**Solución**:
1. Eliminar todos los archivos Parquet antiguos del bucket
2. Regenerar todos los archivos con `json_to_parquet.py` usando el orden correcto
3. Eliminar y recrear la tabla externa en BigQuery

## Pipeline de Transformación

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Information    │     │   GCS Raw Layer  │     │ GCS Processed   │
│    Tracer API   │────▶│  (JSONs)         │────▶│ (Parquet)       │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                │                         │
                                │                         │
                                ▼                         ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   Firestore      │     │    BigQuery     │
                        │   (metadata)     │     │ (External Table)│
                        └──────────────────┘     └─────────────────┘
```

### Script de transformación

**Nota**: Solo procesa archivos con estructura `raw/{country}/{platform}/{candidate_id}/{post_id}.json`.
Archivos directamente en `raw/{country}/{platform}/` son ignorados automáticamente.

```bash
# Procesar todos los JSONs de Honduras/Twitter
poetry run python scripts/json_to_parquet.py \
  --bucket trust-prd \
  --country honduras \
  --platform twitter \
  --upload

# Filtrar por candidato
poetry run python scripts/json_to_parquet.py \
  --bucket trust-prd \
  --country honduras \
  --platform twitter \
  --candidate-id hnd01monc \
  --upload

# Dry run (ver qué se procesaría)
poetry run python scripts/json_to_parquet.py \
  --bucket trust-prd \
  --country honduras \
  --platform twitter \
  --dry-run
```

## BigQuery External Tables

### Creación con Terraform

```bash
cd terraform
terraform init
terraform apply \
  -var="project_id=trust-481601" \
  -var="gcs_bucket=trust-prd" \
  -var="region=us-east1"
```

### Creación manual (SQL)

```sql
-- Crear dataset
CREATE SCHEMA IF NOT EXISTS `trust-481601.trust_analytics`;

-- Crear external table con particiones Hive
CREATE EXTERNAL TABLE `trust-481601.trust_analytics.replies`
WITH PARTITION COLUMNS (
  ingestion_date DATE,
  platform STRING
)
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://trust-prd/processed/replies/*'],
  hive_partition_uri_prefix = 'gs://trust-prd/processed/replies/'
);
```

### Queries de ejemplo

```sql
-- Todas las replies de un candidato
SELECT * 
FROM `trust-481601.trust_analytics.replies`
WHERE candidate_id = 'hnd01monc'
ORDER BY ingestion_date DESC
LIMIT 100;

-- Engagement por día (usa pruning de particiones)
SELECT 
  ingestion_date,
  candidate_id,
  COUNT(*) as total_replies,
  SUM(favorite_count) as total_favorites,
  AVG(favorite_count) as avg_favorites
FROM `trust-481601.trust_analytics.replies`
WHERE ingestion_date BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY ingestion_date, candidate_id
ORDER BY ingestion_date DESC;

-- Top usuarios que más responden
SELECT 
  user_screen_name,
  COUNT(*) as reply_count,
  SUM(favorite_count) as total_favorites
FROM `trust-481601.trust_analytics.replies`
WHERE candidate_id = 'hnd01monc'
GROUP BY user_screen_name
ORDER BY reply_count DESC
LIMIT 20;

-- Análisis de sentimiento por idioma
SELECT 
  lang,
  COUNT(*) as count,
  AVG(favorite_count) as avg_favorites
FROM `trust-481601.trust_analytics.replies`
WHERE platform = 'twitter'
GROUP BY lang
ORDER BY count DESC;
```

## Vistas Predefinidas

El Terraform crea estas vistas automáticamente:

| Vista | Descripción |
|-------|-------------|
| `twitter_replies` | Solo replies de Twitter |
| `instagram_replies` | Solo replies de Instagram |
| `daily_engagement` | Métricas diarias por candidato |
| `candidate_summary` | Resumen total por candidato |

## Costos

### BigQuery External Tables

- **Storage**: $0 (datos permanecen en GCS)
- **Queries**: ~$5 por TB escaneado
- **Particiones**: Reducen bytes escaneados significativamente

### Optimizaciones de costo

1. **Siempre filtrar por partición** (`ingestion_date`, `platform`)
2. **Seleccionar solo columnas necesarias** (evitar `SELECT *`)
3. **Usar `LIMIT`** en queries exploratorios
4. **Materializar** tablas si hay queries repetitivos

### Ejemplo de ahorro

```sql
-- ❌ Malo: escanea todo (~$0.50 por 100GB)
SELECT * FROM `trust_analytics.replies`;

-- ✅ Bueno: escanea solo 1 día (~$0.01)
SELECT tweet_id, full_text, favorite_count
FROM `trust_analytics.replies`
WHERE ingestion_date = '2026-01-05'
  AND platform = 'twitter';
```

## Automatización

### Cloud Scheduler + Cloud Function

Para mantener el Parquet actualizado automáticamente:

1. **Cloud Scheduler**: Trigger diario a las 2:00 AM
2. **Cloud Function**: Ejecuta `json_to_parquet.py`
3. **Solo procesa nuevos archivos**: Basado en `last_modified > last_run`

### Ejemplo de Cloud Function

```python
def transform_to_parquet(event, context):
    """Triggered by Cloud Scheduler."""
    import subprocess
    
    subprocess.run([
        "python", "scripts/json_to_parquet.py",
        "--bucket", "trust-prd",
        "--country", "honduras",
        "--upload"
    ], check=True)
```

## Monitoreo

### Métricas a monitorear

- Cantidad de archivos procesados por día
- Tamaño de particiones Parquet
- Latencia de queries en BigQuery
- Errores de transformación

### Alertas sugeridas

- Partición vacía (no hay datos nuevos)
- Error de transformación
- Query timeout en BigQuery

