# Optimizaciones del Endpoint `/json-to-parquet`

Este documento explica las optimizaciones implementadas en el endpoint `POST /json-to-parquet` del servicio `scrapping-tools` para lograr una conversión eficiente de JSONs a Parquet con carga incremental.

## Resumen Ejecutivo

El endpoint `/json-to-parquet` convierte archivos JSON desde la capa `raw/` de GCS a formato Parquet en la capa `processed/replies/` con las siguientes optimizaciones:

1. **Filtrado por timestamp**: Solo procesa JSONs nuevos comparando timestamps con Parquet existentes
2. **Lectura selectiva**: Usa metadata de GCS sin descargar contenido innecesario
3. **Carga incremental**: Fusiona nuevos registros con existentes sin sobreescribir
4. **Deduplicación eficiente**: Evita duplicados usando claves únicas

## Arquitectura del Endpoint

### Flujo de Procesamiento

```
1. Pre-fetch timestamps de Parquet existentes
   ↓
2. Listar JSONs en GCS (solo metadata)
   ↓
3. Filtrar JSONs por timestamp (skip si ya procesados)
   ↓
4. Descargar solo JSONs nuevos
   ↓
5. Procesar y agrupar por partición (fecha/plataforma)
   ↓
6. Leer Parquet existente por partición (si existe)
   ↓
7. Fusionar y deduplicar registros
   ↓
8. Escribir Parquet actualizado a GCS
```

## Optimizaciones Detalladas

### 1. Filtrado Inteligente por Timestamp (Optimización Principal)

**Problema**: Sin esta optimización, el endpoint procesaría todos los JSONs del bucket en cada ejecución, incluso aquellos que ya fueron convertidos.

**Problema adicional identificado**: Usar `blob.updated` del archivo Parquet es incorrecto porque este timestamp se actualiza cada vez que se reescribe el Parquet (incluso durante merge incremental), lo que hace que el filtro no funcione correctamente para carga incremental.

**Solución**: Comparación usando **MAX(ingestion_timestamp) de los registros dentro del Parquet** (no `blob.updated`), con carga diferida (lazy loading) y buffer de seguridad:

1. **JSON dentro de 1 hora del MAX(ingestion_timestamp) del Parquet o más nuevo** → Procesar (puede tener datos nuevos)
2. **JSON más de 1 hora más antiguo que MAX(ingestion_timestamp) del Parquet** → Skip (probablemente ya procesado)
3. **Deduplicación por `(source_file, tweet_id)`** → Respaldo final para evitar duplicados

Esta estrategia es eficiente y correcta porque:
- Usa MAX(ingestion_timestamp) de los registros del Parquet, que refleja el timestamp real de los datos procesados
- `blob.updated` se actualiza cada vez que se escribe el Parquet (no refleja cuándo se procesaron los datos)
- Carga diferida (lazy loading): solo lee Parquet cuando encuentra JSONs para esa partición, evitando leer todos los Parquet upfront
- Usa un buffer de 1 hora para evitar saltar JSONs que aún no han sido procesados
- Compara dentro de la misma partición `(ingestion_date, platform)`
- La deduplicación asegura que no se creen duplicados como medida de seguridad adicional

**Implementación**:

```python
# Build set of existing partitions (solo listar, sin leer contenido)
existing_partitions: set[tuple[str, str]] = set()
for parquet_blob in bucket.list_blobs(prefix="marts/replies/ingestion_date="):
    if parquet_blob.name.endswith(".parquet"):
        date_part, platform_part = extract_partition(parquet_blob.name)
        existing_partitions.add((date_part, platform_part))

# Cache para max ingestion_timestamps (lazy-loaded)
parquet_max_timestamps: dict[tuple[str, str], datetime | None] = {}

# Filtrar JSONs con carga diferida de timestamps
for blob in json_blobs:
    blob.reload()  # Solo metadata
    ingestion_ts = blob.updated
    date_str = ingestion_ts.strftime("%Y-%m-%d")
    partition_key = (date_str, platform_from_path)
    
    if not skip_timestamp_filter and partition_key in existing_partitions:
        # Lazy-load max ingestion_timestamp solo cuando se necesita
        if partition_key not in parquet_max_timestamps:
            max_ts = _get_parquet_max_ingestion_timestamp(bucket, date_str, platform)
            parquet_max_timestamps[partition_key] = max_ts
        
        max_ts = parquet_max_timestamps[partition_key]
        if max_ts is not None:
            buffer = timedelta(hours=1)
            if ingestion_ts < (max_ts - buffer):
                # JSON más de 1 hora más antiguo que MAX(ingestion_timestamp) → skip
                continue
    
    # JSON dentro de 1 hora del MAX o más nuevo (o Parquet no existe) → procesar
    data = blob.download_as_text()
    json_files.append((blob.name, data, ingestion_ts))

# Función auxiliar para obtener MAX(ingestion_timestamp) del Parquet
def _get_parquet_max_ingestion_timestamp(bucket, date_str, platform):
    """Lee Parquet y retorna MAX(ingestion_timestamp) usando PyArrow compute."""
    blob_path = f"marts/replies/ingestion_date={date_str}/platform={platform}/data.parquet"
    parquet_data = bucket.blob(blob_path).download_as_bytes()
    table = pq.read_table(io.BytesIO(parquet_data))
    
    # Usar PyArrow compute para obtener MAX eficientemente
    import pyarrow.compute as pc
    max_ts = pc.max(table.column("ingestion_timestamp")).as_py()
    return max_ts if isinstance(max_ts, datetime) else None

# Merge con deduplicación (respaldo final)
for (date_str, platform), new_records in records_by_partition.items():
    existing_records, _ = _read_existing_parquet_from_gcs(...)
    # Deduplicación por (source_file, tweet_id)...
```

**Beneficios**:
- **Eficiencia**: Solo descarga JSONs que son más nuevos que el MAX(ingestion_timestamp) del Parquet (99% menos I/O en ejecuciones incrementales)
- **Correctitud**: Usa el timestamp real de los datos (ingestion_timestamp) en lugar del timestamp del archivo (blob.updated)
- **Carga diferida**: Solo lee Parquet cuando encuentra JSONs para esa partición, evitando leer todos los Parquet upfront
- **Precisión**: MAX(ingestion_timestamp) refleja el dato más reciente procesado, no cuándo se escribió el archivo
- **Simplicidad**: Lógica directa y fácil de entender
- **Deduplicación eficiente**: O(1) lookup usando sets como respaldo final
- **Escalabilidad**: Reduce procesamiento proporcionalmente con el volumen de datos

**Métricas**:
- **Filtrado**: Solo descarga JSONs dentro de 1 hora del MAX(ingestion_timestamp) del Parquet o más nuevos para su fecha de ingesta
- **Lectura Parquet**: Solo lee Parquet de particiones donde hay JSONs nuevos (lazy loading)
- **Deduplicación**: O(1) lookup por registro (respaldo)
- **Mejora**: Reduce significativamente las descargas en ejecuciones incrementales, evitando procesar JSONs muy antiguos

### 2. Carga Incremental con Merge Inteligente

**Problema**: Sobreescribir Parquet existentes perdería datos históricos y sería ineficiente.

**Solución**: Leer Parquet existente, fusionar con nuevos registros usando deduplicación, y escribir el resultado actualizado.

**Implementación**:

```python
# Leer Parquet existente solo si hay JSONs nuevos para esa partición
existing_records, _ = _read_existing_parquet_from_gcs(bucket, date_str, platform)

if existing_records:
    # Crear set de claves existentes para deduplicación O(1)
    existing_keys = {
        (r["source_file"], r["tweet_id"]) 
        for r in existing_records
    }
    
    # Agregar solo registros nuevos
    new_count = 0
    for record in new_records:
        key = (record["source_file"], record["tweet_id"])
        if key not in existing_keys:
            existing_records.append(record)
            existing_keys.add(key)
            new_count += 1
    
    all_records = existing_records
else:
    all_records = new_records

# Escribir Parquet fusionado
_write_parquet_to_gcs(all_records, bucket, date_str, platform)
```

**Beneficios**:
- **Preservación de datos**: No se pierden registros históricos
- **Deduplicación eficiente**: O(1) lookup usando sets de Python
- **Merge inteligente**: Solo agrega registros realmente nuevos
- **Correctitud**: Maneja correctamente JSONs generados después de actualización del Parquet

**Complejidad**:
- **Lectura Parquet**: O(n) donde n = registros existentes
- **Deduplicación**: O(m) donde m = registros nuevos
- **Total**: O(n + m) lineal, eficiente para grandes volúmenes

### 3. Procesamiento Selectivo por Partición

**Problema**: Sobreescribir Parquet existentes perdería datos históricos y sería ineficiente.

**Solución**: Leer Parquet existente, fusionar con nuevos registros, y escribir el resultado actualizado.

**Implementación**:

```python
# Leer Parquet existente solo si hay JSONs nuevos para esa partición
existing_records, _ = _read_existing_parquet_from_gcs(bucket, date_str, platform)

if existing_records:
    # Crear set de claves existentes para deduplicación O(1)
    existing_keys = {
        (r["source_file"], r["tweet_id"]) 
        for r in existing_records
    }
    
    # Agregar solo registros nuevos
    for record in new_records:
        key = (record["source_file"], record["tweet_id"])
        if key not in existing_keys:
            existing_records.append(record)
            existing_keys.add(key)  # Actualizar set
    
    all_records = existing_records
else:
    all_records = new_records

# Escribir Parquet fusionado
_write_parquet_to_gcs(all_records, bucket, date_str, platform)
```

**Beneficios**:
- **Preservación de datos**: No se pierden registros históricos
- **Deduplicación eficiente**: O(1) lookup usando sets de Python
- **Merge inteligente**: Solo agrega registros realmente nuevos

**Complejidad**:
- **Lectura Parquet**: O(n) donde n = registros existentes
- **Deduplicación**: O(m) donde m = registros nuevos
- **Total**: O(n + m) lineal, eficiente para grandes volúmenes

### 4. Procesamiento Selectivo por Partición

**Problema**: Procesar todas las particiones incluso cuando solo algunas tienen cambios nuevos.

**Solución**: Agrupar JSONs por partición `(ingestion_date, platform)` y solo leer/escribir Parquet para particiones con cambios. Esto reduce I/O innecesario.

**Implementación**:

```python
# Agrupar por partición antes de procesar
records_by_partition: dict[tuple[str, str], list[dict]] = {}

for blob_name, data, ingestion_ts in json_files:
    flattened, platform = process_json_file(data, blob_name, ingestion_ts)
    date_str = ingestion_ts.strftime("%Y-%m-%d")
    key = (date_str, platform)
    
    if key not in records_by_partition:
        records_by_partition[key] = []
    records_by_partition[key].extend(flattened)

# Solo procesar particiones con cambios
for (date_str, platform), new_records in records_by_partition.items():
    # Solo aquí leemos Parquet existente para esta partición
    existing_records, _ = _read_existing_parquet_from_gcs(...)
    # ... merge y write
```

**Beneficios**:
- **Lectura selectiva**: Solo lee Parquet de particiones afectadas
- **Escritura selectiva**: Solo escribe particiones que cambiaron
- **Eficiencia**: Si 1000 JSONs afectan 5 particiones, solo lee 5 Parquet (no todos)

**Ejemplo**:
- **Escenario**: 1000 JSONs nuevos distribuidos en 5 particiones (fechas/plataformas)
- **Parquet existentes**: 20 particiones en total
- **Sin optimización**: Lee/escribe 20 Parquet
- **Con optimización**: Lee/escribe solo 5 Parquet afectados
- **Mejora**: 75% menos operaciones I/O

## Métricas de Rendimiento

### Escenario de Prueba

**Configuración**:
- Total JSONs en bucket: 10,000
- JSONs nuevos desde última ejecución: 100
- Tamaño promedio JSON: 50 KB
- Registros por JSON: ~100
- Particiones afectadas: 3 (fechas/plataformas diferentes)
- Registros existentes en Parquet: ~900,000

### Comparación: Sin vs Con Optimizaciones

| Métrica | Sin Optimizaciones | Con Optimizaciones | Mejora |
|---------|-------------------|-------------------|--------|
| **JSONs descargados** | 10,000 | ~100 | 99% menos |
| **Registros procesados** | ~1,000,000 | ~10,000 | 99% menos |
| **Parquet leídos** | 0 (sobrescribe) | 3 (solo afectados) | Incremental |
| **Parquet escritos** | 20 (todos) | 3 (solo afectados) | 85% menos |
| **Tiempo estimado** | ~30 minutos | ~2 minutos | 93% más rápido |
| **Ancho de banda** | ~500 MB | ~5 MB | 99% menos |
| **Deduplicación** | No (duplicados) | Sí (O(1) lookup) | Correctitud |
| **Correctitud** | ❌ Pierde datos nuevos | ✅ Siempre actualiza | Crítico |

### Escalabilidad

**Crecimiento lineal**: Las optimizaciones escalan bien con el volumen de datos:

| Total JSONs | JSONs Nuevos | Registros Existentes | Tiempo Sin Opt | Tiempo Con Opt | Factor Mejora |
|-------------|--------------|---------------------|----------------|----------------|---------------|
| 1,000 | 10 | 90,000 | 3 min | 0.2 min | 15x |
| 10,000 | 100 | 900,000 | 30 min | 2 min | 15x |
| 100,000 | 1,000 | 9,000,000 | 5 horas | 20 min | 15x |
| 1,000,000 | 10,000 | 90,000,000 | 50 horas | 3.3 horas | 15x |

**Observación**: El factor de mejora se mantiene constante porque el filtrado inteligente reduce proporcionalmente el procesamiento. La ventana de seguridad de 24h asegura correctitud mientras mantiene alta eficiencia.

## Limitaciones y Consideraciones

### 1. Comparación por Partición de Ingesta con MAX(ingestion_timestamp)

**Comportamiento**: Los JSONs se comparan con el MAX(ingestion_timestamp) del Parquet de su misma partición `(ingestion_date, platform)`.

**Razón**: Cada JSON tiene una fecha de ingesta (del `blob.updated`), y se compara con el máximo `ingestion_timestamp` de los registros dentro del Parquet correspondiente a esa fecha. Esto asegura que:
- JSONs nuevos para una fecha se procesen correctamente
- JSONs antiguos ya procesados se salten eficientemente
- No se mezclen comparaciones entre diferentes fechas de ingesta
- El filtro funciona correctamente incluso cuando el Parquet se reescribe frecuentemente (merge incremental)

**Ejemplo**:
```python
# Escenario:
# 1. Parquet para 2026-01-05/twitter contiene registros con MAX(ingestion_timestamp) = 2026-01-05 07:00:00
# 2. JSON con ingestion_date=2026-01-05 creado a las 10:00 AM:
#    - JSON.updated (10:00 AM) > MAX(ingestion_timestamp) (7:00 AM) → Procesar ✅
# 3. JSON con ingestion_date=2026-01-05 creado a las 6:00 AM:
#    - JSON.updated (6:00 AM) < MAX(ingestion_timestamp) - 1h (6:00 AM) → Skip ✅
#    
# Nota: blob.updated del Parquet podría ser 2026-01-05 15:00:00 (cuando se hizo merge),
#       pero usamos MAX(ingestion_timestamp) = 2026-01-05 07:00:00 para la comparación
```

### 2. Eficiencia vs Correctitud

**Trade-off**: Procesamos todos los JSONs cada vez para garantizar correctitud, en lugar de optimizar por velocidad.

**Razón**: Es más importante asegurar que todos los datos se procesen correctamente que ahorrar tiempo de procesamiento.

**Mitigación**: 
- La deduplicación es O(1) lookup, muy eficiente
- Solo escribimos particiones que tienen cambios
- El merge es en memoria, rápido

**Recomendación**: Para cargas iniciales muy grandes (millones de JSONs), considerar ejecutar en lotes por país/plataforma usando los filtros del endpoint.

### 3. Primera Ejecución

**Comportamiento**: En la primera ejecución, no hay Parquet existentes, por lo que procesa todos los JSONs y crea nuevos Parquet.

**Esperado**: Este es el comportamiento correcto para la carga inicial.

**Recomendación**: Para cargas iniciales grandes, considerar ejecutar en lotes por país/plataforma usando los filtros del endpoint.

### 4. Parámetro `skip_timestamp_filter` (Modo Seguro)

**Problema**: En algunos casos, el filtro por timestamp puede ser demasiado agresivo y saltar JSONs nuevos que deberían procesarse (por ejemplo, si tienen timestamps más antiguos que el Parquet).

**Solución**: Parámetro `skip_timestamp_filter` que permite deshabilitar el filtro por timestamp y confiar solo en la deduplicación.

**Comportamiento**:
- `skip_timestamp_filter=false` (por defecto): Usa optimización de timestamp - procesa JSONs que están dentro de 1 hora del MAX(ingestion_timestamp) del Parquet o más nuevos (evita procesar JSONs más de 1 hora más antiguos)
- `skip_timestamp_filter=true`: Procesa todos los JSONs sin filtrar por timestamp, confía solo en deduplicación por `(source_file, tweet_id)`

**Cuándo usar `skip_timestamp_filter=true`**:
- Si los JSONs nuevos no se están procesando debido a problemas con timestamps (aunque esto debería ser raro con el buffer de 1 hora)
- Si necesitas garantizar que todos los JSONs se procesen (modo seguro)
- Si prefieres confiar en la deduplicación en lugar del filtro por timestamp
- Si tienes JSONs muy antiguos que necesitas procesar y que serían saltados por el filtro

**Trade-offs**:
- **Ventaja**: Garantiza que todos los JSONs se procesen, incluso si tienen timestamps antiguos
- **Desventaja**: Menos eficiente - descarga y procesa todos los JSONs en cada ejecución
- **Mitigación**: La deduplicación es muy eficiente (O(1) lookup), por lo que el costo adicional es principalmente I/O

**Ejemplo**:
```bash
# Modo optimizado (por defecto)
POST /json-to-parquet

# Modo seguro (procesa todos los JSONs)
POST /json-to-parquet?skip_timestamp_filter=true
```

### 5. Filtros Opcionales

**Filtros disponibles**: `country`, `platform`, `candidate_id`

**Efecto**: Los filtros reducen aún más el procesamiento al limitar qué JSONs se consideran.

**Ejemplo**:
```bash
# Procesa solo JSONs de Honduras/Twitter
POST /json-to-parquet?country=honduras&platform=twitter

# Procesa solo un candidato específico
POST /json-to-parquet?country=honduras&platform=twitter&candidate_id=hnd01monc

# Deshabilitar filtro por timestamp (procesa todos los JSONs)
POST /json-to-parquet?skip_timestamp_filter=true
```

### 6. Consistencia de Datos

**Garantía**: La deduplicación asegura que no haya duplicados en el resultado final.

**Clave de deduplicación**: `(source_file, tweet_id)`

**Nota**: Si el mismo tweet aparece en múltiples JSONs (por ejemplo, en reintentos), solo se mantiene una copia.

## Uso del Endpoint

### Ejemplo Básico

```bash
# Convertir todos los JSONs nuevos a Parquet
curl -X POST "http://localhost:8082/json-to-parquet"
```

### Ejemplo con Filtros

```bash
# Solo procesar JSONs de Honduras/Twitter
curl -X POST "http://localhost:8082/json-to-parquet?country=honduras&platform=twitter"

# Solo procesar un candidato específico
curl -X POST "http://localhost:8082/json-to-parquet?country=honduras&platform=twitter&candidate_id=hnd01monc"

# Deshabilitar filtro por timestamp (procesa todos los JSONs, confía en deduplicación)
curl -X POST "http://localhost:8082/json-to-parquet?skip_timestamp_filter=true"
```

### Respuesta del Endpoint

```json
{
  "processed": 100,
  "succeeded": 3,
  "failed": 0,
  "errors": [],
  "written_files": [
    "gs://trust-prd/processed/replies/ingestion_date=2026-01-05/platform=twitter/data.parquet",
    "gs://trust-prd/processed/replies/ingestion_date=2026-01-05/platform=instagram/data.parquet",
    "gs://trust-prd/processed/replies/ingestion_date=2026-01-06/platform=twitter/data.parquet"
  ]
}
```

### Integración en Pipeline

**Flujo recomendado**:

```bash
# 1. Procesar jobs pendientes (genera JSONs)
POST /process-jobs

# 2. Convertir JSONs nuevos a Parquet (con optimizaciones)
POST /json-to-parquet

# 3. Los datos están disponibles en BigQuery automáticamente
```

## Conclusión

Las optimizaciones implementadas hacen que el endpoint `/json-to-parquet` sea:

1. **Eficiente**: Filtrado inteligente reduce I/O en 99% en ejecuciones incrementales típicas
2. **Correcto**: Compara JSONs con Parquet de su misma fecha de ingesta
3. **Confiable**: Deduplicación por `(source_file, tweet_id)` como respaldo final
4. **Escalable**: Mejora proporcionalmente con el volumen de datos

La optimización principal es el **filtrado por timestamp usando MAX(ingestion_timestamp) dentro de la misma partición de ingesta**: solo procesa JSONs que son más nuevos que el máximo `ingestion_timestamp` de los registros en el Parquet para su fecha de ingesta. Esto es más preciso que usar `blob.updated` porque refleja el timestamp real de los datos procesados, no cuándo se escribió el archivo. La deduplicación actúa como respaldo final para garantizar que no se creen duplicados incluso en casos edge.

## Referencias

- [Data Lake Architecture](./DATA_LAKE_ARCHITECTURE.md) - Arquitectura general del data lake
- [Scrapping Tools Service](../src/trust_api/scrapping_tools/main.py) - Implementación del endpoint
- [JSON to Parquet Script](../scripts/json_to_parquet.py) - Script original de referencia

