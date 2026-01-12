# Creación de Tabla Consolidada de Posts

Este documento explica cómo crear la tabla consolidada de posts que combina datos de Firestore con conteos de replies reales desde los archivos Parquet.

## Resumen

El script `create_posts_consolidated.py` crea una tabla consolidada que:

1. **Lee posts de Firestore**: Obtiene todos los posts con sus campos incluyendo `max_replies`
2. **Cuenta replies reales**: Cuenta las replies realmente scrappeadas desde los archivos Parquet usando `parent_post_id`
3. **Genera Parquet consolidado**: Crea archivos Parquet particionados por `ingestion_date` y `platform`
4. **Sube a GCS**: Opcionalmente sube los archivos a la capa `marts/posts/` para consumo desde BigQuery

## Requisitos Previos

- Python 3.12+
- Dependencias instaladas: `poetry install`
- Autenticación con GCP configurada (ADC o service account)
- Acceso a:
  - Firestore (colección `posts` en base de datos `socialnetworks`)
  - GCS bucket con archivos Parquet de replies en `marts/replies/`

## Uso Básico

### Procesar posts y guardar Parquet localmente

```bash
poetry run python scripts/create_posts_consolidated.py --bucket trust-prd
```

Esto:
- Lee todos los posts de Firestore
- Cuenta replies desde Parquet (puede tardar si hay muchos archivos)
- Guarda Parquet en `./data/processed/posts/`

### Procesar y subir a GCS

```bash
poetry run python scripts/create_posts_consolidated.py --bucket trust-prd --upload
```

Esto hace lo mismo pero además sube los archivos a `gs://trust-prd/marts/posts/`

### Dry run (sin escribir archivos)

```bash
poetry run python scripts/create_posts_consolidated.py --bucket trust-prd --dry-run
```

Útil para verificar qué se procesaría sin hacer cambios.

### Saltar conteo de replies (más rápido)

```bash
poetry run python scripts/create_posts_consolidated.py --bucket trust-prd --skip-reply-count
```

Esto establece `real_replies_count = 0` para todos los posts, pero es mucho más rápido. Útil para pruebas o cuando solo necesitas la estructura de datos.

## Opciones Avanzadas

### Especificar proyecto GCP

```bash
poetry run python scripts/create_posts_consolidated.py \
  --bucket trust-prd \
  --project-id trust-481601
```

### Cambiar base de datos o colección de Firestore

```bash
poetry run python scripts/create_posts_consolidated.py \
  --bucket trust-prd \
  --database socialnetworks \
  --collection posts
```

### Cambiar directorio de salida

```bash
poetry run python scripts/create_posts_consolidated.py \
  --bucket trust-prd \
  --output-dir ./custom/output/path
```

## Estructura de Datos

### Schema de la Tabla Consolidada

La tabla incluye los siguientes campos:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `post_id` | STRING | ID único del post en la red social |
| `country` | STRING | País |
| `platform` | STRING | Plataforma (twitter, instagram, etc.) |
| `candidate_id` | STRING | ID del candidato |
| `created_at` | TIMESTAMP | Fecha de creación del post |
| `replies_count` | INTEGER | Número de respuestas del post (desde Firestore) |
| `max_replies` | INTEGER | Máximo de respuestas a recolectar (desde Firestore) |
| `status` | STRING | Estado del post (noreplies, done, skipped, etc.) |
| `updated_at` | TIMESTAMP | Última actualización del documento |
| `real_replies_count` | INTEGER | **Cantidad real de replies scrappeadas** (calculado desde Parquet) |
| `ingestion_date` | DATE | Fecha de ingesta (partición) |
| `ingestion_timestamp` | TIMESTAMP | Timestamp de ingesta |

### Estructura de Particiones

Los archivos Parquet se organizan en particiones:

```
marts/posts/
  platform=twitter/
    ingestion_date=2026-01-15/
      data.parquet
    ingestion_date=2026-01-16/
      data.parquet
  platform=instagram/
    ingestion_date=2026-01-15/
      data.parquet
    ingestion_date=2026-01-16/
      data.parquet
```

**Orden de particiones**: `platform` primero, luego `ingestion_date` (para consistencia con BigQuery).

## Optimizaciones

### Conteo Eficiente de Replies

El script usa una optimización para contar replies:

1. **Pre-computación**: Lee todos los archivos Parquet una sola vez y cuenta replies por `(post_id, platform)`
2. **Cache en memoria**: Almacena los conteos en un diccionario para acceso rápido
3. **Procesamiento por lotes**: Procesa posts en lotes mostrando progreso cada 100 posts

Esto es mucho más eficiente que leer Parquet para cada post individualmente.

## Integración con BigQuery

Después de subir los archivos a GCS, puedes crear una tabla externa en BigQuery usando Terraform:

```bash
cd terraform
terraform plan
terraform apply
```

O manualmente:

```sql
CREATE EXTERNAL TABLE `trust-481601.trust_analytics.posts`
WITH PARTITION COLUMNS (
  platform STRING,
  ingestion_date DATE
)
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://trust-prd/marts/posts/*'],
  hive_partition_uri_prefix = 'gs://trust-prd/marts/posts/'
);
```

## Consultas Útiles en BigQuery

### Ver posts con comparación de max_replies vs real_replies_count

```sql
SELECT 
  post_id,
  country,
  platform,
  candidate_id,
  max_replies,
  real_replies_count,
  (max_replies - real_replies_count) as difference,
  status,
  created_at
FROM `trust-481601.trust_analytics.posts`
WHERE country = 'honduras'
ORDER BY ingestion_date DESC
LIMIT 100;
```

### Resumen por candidato

```sql
SELECT 
  country,
  platform,
  candidate_id,
  COUNT(*) as total_posts,
  SUM(max_replies) as total_max_replies,
  SUM(real_replies_count) as total_real_replies,
  AVG(real_replies_count) as avg_real_replies_per_post,
  SUM(CASE WHEN real_replies_count < max_replies THEN 1 ELSE 0 END) as posts_with_fewer_replies
FROM `trust-481601.trust_analytics.posts`
GROUP BY country, platform, candidate_id
ORDER BY country, platform, candidate_id;
```

### Posts con diferencia significativa

```sql
SELECT 
  post_id,
  country,
  platform,
  candidate_id,
  max_replies,
  real_replies_count,
  (max_replies - real_replies_count) as missing_replies,
  ROUND(100.0 * real_replies_count / NULLIF(max_replies, 0), 2) as completion_percentage
FROM `trust-481601.trust_analytics.posts`
WHERE max_replies > 0
  AND real_replies_count < max_replies
ORDER BY missing_replies DESC
LIMIT 50;
```

## ⚠️ Importante: Orden de Particiones

El orden de particiones es **crítico** para BigQuery. Los archivos deben estar organizados como:

```
marts/posts/platform={platform}/ingestion_date={date}/data.parquet
```

**NO** como:
```
marts/posts/ingestion_date={date}/platform={platform}/data.parquet  ❌
```

Si ya tienes archivos con el orden incorrecto en GCS, debes:

1. **Eliminar los archivos antiguos** de `marts/posts/` con el orden incorrecto
2. **Regenerar los archivos** con el script usando el orden correcto
3. **Recrear la tabla** en BigQuery si es necesario

### Error de particiones inconsistentes

Si ves el error:
```
Partition keys should be invariant from table creation across all partitions
```

**Solución**:
1. Verifica que todos los archivos en `marts/posts/` tengan el mismo orden de particiones
2. Elimina archivos con orden incorrecto
3. Regenera los archivos con el script
4. Recrea la tabla en BigQuery

## Troubleshooting

### Error: "pyarrow is required"

Instala las dependencias:

```bash
poetry add pyarrow
```

### Error: "google-cloud-storage is required"

Instala las dependencias de GCP:

```bash
poetry add google-cloud-storage google-cloud-firestore
```

### Error de autenticación

Verifica que tengas credenciales configuradas:

```bash
# Usar Application Default Credentials
gcloud auth application-default login

# O configurar variable de entorno
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### El proceso es muy lento

Si tienes muchos archivos Parquet, el conteo puede tardar. Opciones:

1. **Usar `--skip-reply-count`**: Más rápido pero sin conteos reales
2. **Procesar por país o plataforma**: Modificar el script para filtrar
3. **Usar BigQuery**: Si los Parquet ya están en BigQuery, puedes hacer el conteo con SQL

### No encuentra replies en Parquet

Verifica que:
- Los archivos Parquet estén en `marts/replies/` (no `processed/replies/`)
- Los archivos tengan la columna `parent_post_id`
- El `post_id` en Firestore coincida con `parent_post_id` en los Parquet

## Automatización

Para ejecutar este proceso periódicamente, puedes:

1. **Cloud Scheduler**: Crear un job que ejecute el script en Cloud Run
2. **Workflow**: Integrar en un workflow de GCP que se ejecute después de procesar replies
3. **Cron local**: Ejecutar manualmente cuando sea necesario

Ejemplo de integración en workflow:

```yaml
# Después de procesar replies a Parquet
- name: create-posts-consolidated
  container:
    image: gcr.io/trust-481601/scrapping-tools:latest
    command: ["poetry", "run", "python", "scripts/create_posts_consolidated.py"]
    args: ["--bucket", "trust-prd", "--upload"]
```

## Notas

- El script lee **todos** los posts de Firestore. Si tienes millones de posts, considera agregar filtros.
- El conteo de replies lee **todos** los archivos Parquet. Para datasets muy grandes, considera usar BigQuery para el conteo.
- Los archivos Parquet se particionan por fecha de ingesta, no por fecha del post original.
- El campo `real_replies_count` se calcula contando registros en Parquet donde `parent_post_id = post_id`.
