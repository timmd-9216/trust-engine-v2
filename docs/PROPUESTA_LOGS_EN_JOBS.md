# Implementación: Referencias a Logs en Jobs (Opcional)

**Estado:** ✅ Implementado  
**Versión:** 2026-01-12  
**Configuración:** Opcional, deshabilitado por defecto

## Contexto Actual

### Situación Actual

1. **Logs de ejecución** se guardan en GCS: `logs/YYYY-MM-DD/HH-MM-SS-{timestamp}.json`
2. **Logs de error** se guardan en GCS: `logs/errors/YYYY-MM-DD/HH-MM-SS-{timestamp}.json`
3. **Los logs se guardan al final** de cada ejecución (`process_posts`, `process_jobs`, `fix_jobs`)
4. **Un archivo de log contiene múltiples jobs** procesados en esa ejecución
5. **Los jobs en Firestore NO tienen referencia** a estos archivos de log

### Problema

Cuando un job falla o necesita debugging:
- ❌ No hay forma directa de encontrar los logs relacionados con ese job
- ❌ Hay que buscar manualmente en GCS por fecha/hora
- ❌ No hay trazabilidad clara entre job y logs
- ❌ Dificulta el análisis de errores (como el diagnóstico de los 2 jobs fallidos)

## Propuesta

### Agregar Campos Opcionales a Jobs

Agregar dos campos opcionales a los documentos de job en Firestore:

```python
{
    # ... campos existentes ...
    "execution_log_file": "gs://bucket/logs/2026-01-11/04-30-05-123.json",  # Opcional
    "error_log_file": "gs://bucket/logs/errors/2026-01-11/04-30-05-456.json",  # Opcional
}
```

### Beneficios

1. ✅ **Trazabilidad directa**: Cada job tiene referencia a los logs de la ejecución que lo procesó
2. ✅ **Debugging más rápido**: Encontrar logs relacionados con un job fallido es inmediato
3. ✅ **Análisis de errores**: Facilita el análisis de patrones de errores
4. ✅ **Auditoría**: Trazabilidad completa de qué ejecución procesó cada job
5. ✅ **Búsqueda eficiente**: Puedes buscar jobs por log file si es necesario

### Consideraciones

1. **Un archivo de log contiene múltiples jobs**: 
   - ✅ Esto es correcto - un job puede tener referencia al log file que contiene su procesamiento
   - ✅ Múltiples jobs pueden tener la misma referencia (fueron procesados en la misma ejecución)

2. **Jobs procesados múltiples veces**:
   - ✅ Cada actualización del job puede agregar/actualizar la referencia al log file más reciente
   - ✅ O mantener un array de log files históricos (más complejo, pero más completo)

3. **Espacio en Firestore**:
   - ✅ Los URIs de GCS son relativamente cortos (~100 caracteres)
   - ✅ Impacto mínimo en costo de almacenamiento

## Implementación Realizada

### ✅ Opción Implementada: Referencia al Log Más Reciente

**Decisión:** Se implementó la Opción 1 (referencia al log más reciente) con las siguientes características:

1. **Opcional y configurable**: La funcionalidad está deshabilitada por defecto
2. **Variable de entorno**: `ENABLE_JOB_LOG_REFERENCES` (default: `false`)
3. **Minimiza escrituras en Firestore**: Solo actualiza jobs si la opción está habilitada
4. **Sin impacto por defecto**: No afecta el rendimiento cuando está deshabilitada

### Configuración

**Variable de entorno:**
```bash
# Habilitar referencias a logs en jobs (default: false)
ENABLE_JOB_LOG_REFERENCES=true
```

**Ubicación:** `src/trust_api/scrapping_tools/core/config.py`

```python
# Job logging configuration
# If True, jobs will be updated with references to execution_log_file and error_log_file
# This increases Firestore write operations but improves traceability
# Default: False (disabled) to minimize Firestore writes
enable_job_log_references: bool = os.getenv("ENABLE_JOB_LOG_REFERENCES", "false").lower() in (
    "true",
    "1",
    "yes",
)
```

### Funciones Implementadas

1. **`update_job_with_log_files()`**: Actualiza un job individual con referencias a logs
2. **`update_jobs_with_log_files()`**: Versión batch para actualizar múltiples jobs

**Características:**
- Verifica `settings.enable_job_log_references` antes de hacer cualquier actualización
- Si está deshabilitado, retorna inmediatamente sin hacer escrituras en Firestore
- Maneja errores silenciosamente para no romper el flujo principal

### Integración en Servicios

**✅ `process_pending_jobs_service()`:**
- Rastrea `job_doc_ids` procesados durante la ejecución
- Al final, después de guardar logs, actualiza todos los jobs procesados con referencias a logs

**✅ `process_posts_service()`:**
- Rastrea `job_doc_ids` creados durante la ejecución
- Al final, después de guardar logs, actualiza todos los jobs creados con referencias a logs

**Nota:** `fix_jobs_service()` no se actualizó porque procesa jobs que ya existen, y los logs de ejecución no son tan relevantes para ese flujo.

### Consideraciones de Rendimiento

**Cuando está deshabilitado (default):**
- ✅ Cero impacto en rendimiento
- ✅ Cero escrituras adicionales en Firestore
- ✅ Cero costo adicional

**Cuando está habilitado:**
- ⚠️ Una escritura adicional por job procesado/creado
- ⚠️ Aumenta el número de operaciones de escritura en Firestore
- ✅ Mejora significativamente la trazabilidad y debugging

**Recomendación:**
- **Deshabilitado por defecto** para minimizar costos y escrituras
- **Habilitar solo cuando se necesite debugging o análisis detallado**
- **Considerar habilitar temporalmente** durante períodos de alta actividad o cuando hay problemas

## Ejemplo de Uso

### Antes (Sin Referencias)
```python
# Job fallido en Firestore
{
    "job_id": "abc123",
    "status": "failed",
    "updated_at": "2026-01-11T04:45:06Z"
}

# Para encontrar logs:
# 1. Buscar manualmente en GCS por fecha (2026-01-11)
# 2. Buscar por hora aproximada (04:30-04:45)
# 3. Abrir múltiples archivos hasta encontrar el job_id
```

### Después (Con Referencias)
```python
# Job fallido en Firestore
{
    "job_id": "abc123",
    "status": "failed",
    "updated_at": "2026-01-11T04:45:06Z",
    "execution_log_file": "gs://bucket/logs/2026-01-11/04-30-05-123.json",
    "error_log_file": "gs://bucket/logs/errors/2026-01-11/04-30-05-456.json"
}

# Para encontrar logs:
# 1. Leer job de Firestore
# 2. Acceder directamente a error_log_file
# 3. Buscar job_id en el archivo
```

## Impacto en el Diagnóstico de Jobs Fallidos

Con esta implementación, el diagnóstico de los 2 jobs fallidos del 2026-01-11 sería más directo:

```python
# Script de diagnóstico mejorado
job = get_job_from_firestore(job_id)

if job.get("error_log_file"):
    # Acceder directamente al log de error
    error_log = read_gcs_file(job["error_log_file"])
    # Buscar entrada específica del job
    job_error = find_job_in_log(error_log, job["job_id"])
    print(f"Error details: {job_error}")
```

## Uso

### Habilitar la Funcionalidad

1. **Agregar variable de entorno:**
   ```bash
   # En .env o variables de entorno del sistema
   ENABLE_JOB_LOG_REFERENCES=true
   ```

2. **Reiniciar el servicio** para que tome la nueva configuración

3. **Los jobs procesados/creados** a partir de ese momento tendrán referencias a logs

### Verificar que Funciona

1. **Procesar algunos jobs** (con la opción habilitada)
2. **Verificar en Firestore** que los jobs tienen los campos:
   - `execution_log_file`: URI del log de ejecución
   - `error_log_file`: URI del log de error (si hay errores)

3. **Ejemplo de job con logs:**
   ```json
   {
     "job_id": "abc123",
     "status": "done",
     "execution_log_file": "gs://bucket/logs/2026-01-12/10-30-45-123.json",
     "error_log_file": null
   }
   ```

### Deshabilitar la Funcionalidad

Simplemente remover o establecer la variable de entorno a `false`:
```bash
ENABLE_JOB_LOG_REFERENCES=false
# o simplemente no definirla (default es false)
```

## Archivos Modificados

1. ✅ `src/trust_api/scrapping_tools/core/config.py` - Agregada configuración
2. ✅ `src/trust_api/scrapping_tools/services.py` - Implementadas funciones y integración
3. ✅ `docs/PROPUESTA_LOGS_EN_JOBS.md` - Documentación actualizada

## Estado de Implementación

- ✅ **Configuración**: Variable de entorno implementada
- ✅ **Funciones**: `update_job_with_log_files()` y `update_jobs_with_log_files()` implementadas
- ✅ **Integración**: Integrado en `process_pending_jobs_service()` y `process_posts_service()`
- ✅ **Documentación**: Documentado en este archivo
- ⏳ **Testing**: Pendiente de pruebas en entorno de desarrollo/staging

## Próximos Pasos (Opcional)

1. ⏳ Probar en entorno de desarrollo/staging
2. ⏳ Actualizar documentación de jobs en Firestore (si existe)
3. ⏳ Considerar agregar índices en Firestore para búsqueda por `execution_log_file` (si es necesario)
