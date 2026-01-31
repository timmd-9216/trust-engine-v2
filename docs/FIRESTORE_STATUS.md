# Estados de las Colecciones Firestore

Este documento describe los estados posibles para las colecciones `posts` y `pending_jobs` en Firestore.

## Colección: `posts`

La colección `posts` almacena información sobre posts de redes sociales que deben ser procesados.

### Estados Posibles

| Estado | Descripción | Cuándo se Asigna |
|--------|-------------|------------------|
| `noreplies` | Post pendiente de procesar | Estado inicial cuando se crea un post en Firestore. Indica que el post aún no ha sido enviado a Information Tracer para obtener sus respuestas. También se asigna cuando un job falla y no hay otros jobs pendientes/processing para el mismo post. **NOTA:** Los jobs con `empty_result` NO actualizan automáticamente el post a `noreplies` para evitar retry automático. |
| `processing` | Post en proceso | Se asigna cuando se crea un job para el post. Indica que hay un job pendiente o en procesamiento para este post, evitando la creación de jobs duplicados. Es un estado transitorio. |
| `done` | Post procesado exitosamente | Se asigna cuando el job asociado al post se completa exitosamente y los resultados (respuestas) se guardan correctamente en GCS. |
| `skipped` | Post saltado | Se asigna cuando `max_posts_replies <= 0` y `replies_count <= 0`, lo que indica que no se deben recolectar respuestas para este post. |

### Flujo de Estados

```
noreplies → processing  (cuando se crea un job para el post)
processing → done       (si el job se completa exitosamente)
processing → noreplies  (si el job falla y no hay otros jobs pendientes/processing)
noreplies → skipped     (si max_posts_replies <= 0 y replies_count <= 0)
```

### Ejemplos de Uso

```python
from google.cloud import firestore
from datetime import datetime, timezone

client = firestore.Client(project="trust-481601", database="socialnetworks")

# Consultar posts pendientes
posts = client.collection("posts").where("status", "==", "noreplies").stream()

# Actualizar status a done
doc_ref = client.collection("posts").document("DOCUMENT_ID")
doc_ref.update({
    "status": "done",
    "updated_at": datetime.now(timezone.utc)
})

# Actualizar status a skipped
doc_ref.update({
    "status": "skipped",
    "updated_at": datetime.now(timezone.utc)
})
```

---

## Colección: `pending_jobs`

La colección `pending_jobs` almacena los jobs de Information Tracer que están siendo procesados.

### Estados Posibles

| Estado | Descripción | Cuándo se Asigna |
|--------|-------------|------------------|
| `pending` | Job pendiente de procesar | Estado inicial cuando se crea un job después de hacer submit a Information Tracer. También se asigna cuando un job tiene status "timeout" o desconocido, indicando que debe reintentarse. |
| `processing` | Job en proceso de verificación | Se asigna cuando el sistema comienza a verificar el status del job con Information Tracer API. Es un estado transitorio. |
| `done` | Job completado exitosamente | Se asigna cuando el job se completa exitosamente, los resultados se obtienen de Information Tracer, se validan como no vacíos y se guardan correctamente en GCS. |
| `failed` | Job falló al procesar | Se asigna cuando: (1) Information Tracer API reporta que el job falló y la quota NO está excedida, (2) no se pueden obtener los resultados (result es None) y la quota NO está excedida, o (3) ocurre una excepción durante el procesamiento y la quota NO está excedida. |
| `quota_exceeded` | Job falló por quota excedida | Se asigna cuando Information Tracer API reporta que el job falló Y la verificación de quota muestra que se alcanzó el límite diario (searches_used >= max_searches_per_day). Este status es diferente de `failed` porque indica un problema temporal (quota) que se resolverá al día siguiente, mientras que `failed` indica un fallo permanente del job. |
| `empty_result` | Job completado pero resultado vacío | Se asigna cuando el job se completa exitosamente según Information Tracer (status="finished"), pero el resultado obtenido está vacío (lista vacía o diccionario vacío). Este es un caso especial que se distingue de "failed" porque el job técnicamente terminó, pero no hay datos útiles. |
| `verified` | Job verificado como resultado vacío esperado | Se asigna cuando un job tiene status `empty_result`, la plataforma es `twitter`, y el `replies_count` del post asociado es <= 2. Indica que el resultado vacío es esperado porque el post tiene pocas o ninguna respuesta. |

### Flujo de Estados

```
pending → processing → done           (si el job se completa exitosamente)
pending → processing → failed         (si Information Tracer reporta fallo y quota NO excedida)
pending → processing → quota_exceeded (si Information Tracer reporta fallo y quota está excedida)
pending → processing → empty_result   (si el resultado está vacío)
pending → processing → pending        (si el job tiene timeout, se reintenta)
empty_result → verified               (si platform='twitter' y replies_count <= 2)
```

### Diferencias entre `failed` y `empty_result`

- **`failed`**: El job no se completó correctamente Y la quota NO está excedida. Puede deberse a:
  - Information Tracer API reportó que el job falló (pero quota disponible)
  - No se pudieron obtener los resultados (error de conexión, API error, etc.) y quota disponible
  - Ocurrió una excepción durante el procesamiento y quota disponible

- **`quota_exceeded`**: El job no se completó correctamente porque la quota diaria está excedida. Se diferencia de `failed` porque:
  - Es un problema temporal que se resolverá cuando se resetee la quota (generalmente al día siguiente)
  - Permite identificar trabajos que podrían reintentarse automáticamente cuando haya quota disponible
  - Se detecta verificando el estado de la cuenta con `check_api_usage()` cuando Information Tracer reporta "failed"

- **`empty_result`**: El job se completó técnicamente (Information Tracer reportó "finished"), pero el resultado está vacío. Esto puede ocurrir cuando:
  - El post no tiene respuestas reales
  - Information Tracer no encontró resultados que coincidan con la query
  - El resultado es una lista o diccionario vacío
  - **IMPORTANTE:** Los jobs con `empty_result` NO actualizan automáticamente el post a `noreplies`, evitando retry automático. Para reintentar estos jobs, usar el endpoint `/empty-result-jobs/retry` manualmente.

### Ejemplos de Uso

```python
from google.cloud import firestore
from datetime import datetime, timezone

client = firestore.Client(project="trust-481601", database="socialnetworks")

# Consultar jobs pendientes
jobs = client.collection("pending_jobs").where("status", "==", "pending").stream()

# Consultar jobs fallidos (todos)
failed_jobs = client.collection("pending_jobs").where("status", "==", "failed").stream()

# Para contar solo jobs failed SIN otro job en done para el mismo post_id (candidatos a reintentar),
# usar la API: GET /jobs/count?status=failed&failed_without_done=true
# o el script: list_failed_jobs_without_done.py (ver docs/subir-posts.md)

# Consultar jobs con resultado vacío
empty_jobs = client.collection("pending_jobs").where("status", "==", "empty_result").stream()

# Consultar jobs verificados
verified_jobs = client.collection("pending_jobs").where("status", "==", "verified").stream()

# Actualizar status a done
doc_ref = client.collection("pending_jobs").document("DOCUMENT_ID")
doc_ref.update({
    "status": "done",
    "updated_at": datetime.now(timezone.utc)
})
```

---

## Resumen de Cambios de Estado

### Transiciones de `posts`

| Desde | Hacia | Condición |
|-------|-------|-----------|
| `noreplies` | `processing` | Se crea un job para el post |
| `processing` | `done` | Job completado exitosamente |
| `processing` | `noreplies` | Job falla (no `empty_result`) y no hay otros jobs pendientes/processing |
| `noreplies` | `skipped` | `max_posts_replies <= 0` y `replies_count <= 0` |

### Transiciones de `pending_jobs`

| Desde | Hacia | Condición |
|-------|-------|-----------|
| `pending` | `processing` | Inicio de verificación del job |
| `processing` | `done` | Job completado exitosamente con resultados no vacíos |
| `processing` | `failed` | Information Tracer reporta fallo, error al obtener resultados, o excepción, Y quota NO está excedida |
| `processing` | `quota_exceeded` | Information Tracer reporta fallo Y verificación de quota muestra límite diario alcanzado (searches_used >= max_searches_per_day) |
| `processing` | `empty_result` | Job completado pero resultado vacío |
| `processing` | `pending` | Job con timeout o status desconocido (se reintenta) |
| `empty_result` | `verified` | Platform es 'twitter' y replies_count del post <= 2 (resultado vacío esperado). **Nota**: Cuando un job se verifica, el post asociado también se actualiza a `done`. |

---

## Notas Importantes

1. **Sincronización**: 
   - Cuando un job en `pending_jobs` cambia a `done`, el post asociado en `posts` también cambia a `done`.
   - Cuando un job en `pending_jobs` cambia a `verified` (mediante el script de verificación), el post asociado también cambia a `done` (ya que el resultado vacío es esperado).

2. **Índices**: Para consultas eficientes, se requieren índices compuestos:
   - `posts`: `status + platform + created_at`
   - `pending_jobs`: `status + created_at`, `status + updated_at`

3. **Timestamps**: Todos los cambios de estado actualizan automáticamente el campo `updated_at` con la fecha/hora UTC actual.

4. **Consulta de Jobs Fallidos**: Para analizar jobs fallidos, se puede consultar tanto `status="failed"` como `status="empty_result"` para obtener una vista completa de los problemas.

