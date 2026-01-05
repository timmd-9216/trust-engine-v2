# Estados de las Colecciones Firestore

Este documento describe los estados posibles para las colecciones `posts` y `pending_jobs` en Firestore.

## Colección: `posts`

La colección `posts` almacena información sobre posts de redes sociales que deben ser procesados.

### Estados Posibles

| Estado | Descripción | Cuándo se Asigna |
|--------|-------------|------------------|
| `noreplies` | Post pendiente de procesar | Estado inicial cuando se crea un post en Firestore. Indica que el post aún no ha sido enviado a Information Tracer para obtener sus respuestas. |
| `done` | Post procesado exitosamente | Se asigna cuando el job asociado al post se completa exitosamente y los resultados (respuestas) se guardan correctamente en GCS. |
| `skipped` | Post saltado | Se asigna cuando `max_replies <= 0` y `replies_count <= 0`, lo que indica que no se deben recolectar respuestas para este post. |

### Flujo de Estados

```
noreplies → done        (si el job se completa exitosamente)
noreplies → skipped     (si max_replies <= 0 y replies_count <= 0)
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
| `failed` | Job falló al procesar | Se asigna cuando: (1) Information Tracer API reporta que el job falló, (2) no se pueden obtener los resultados (result es None), o (3) ocurre una excepción durante el procesamiento. |
| `empty_result` | Job completado pero resultado vacío | Se asigna cuando el job se completa exitosamente según Information Tracer (status="finished"), pero el resultado obtenido está vacío (lista vacía o diccionario vacío). Este es un caso especial que se distingue de "failed" porque el job técnicamente terminó, pero no hay datos útiles. |

### Flujo de Estados

```
pending → processing → done          (si el job se completa exitosamente)
pending → processing → failed        (si Information Tracer reporta fallo)
pending → processing → empty_result  (si el resultado está vacío)
pending → processing → pending       (si el job tiene timeout, se reintenta)
```

### Diferencias entre `failed` y `empty_result`

- **`failed`**: El job no se completó correctamente. Puede deberse a:
  - Information Tracer API reportó que el job falló
  - No se pudieron obtener los resultados (error de conexión, API error, etc.)
  - Ocurrió una excepción durante el procesamiento

- **`empty_result`**: El job se completó técnicamente (Information Tracer reportó "finished"), pero el resultado está vacío. Esto puede ocurrir cuando:
  - El post no tiene respuestas reales
  - Information Tracer no encontró resultados que coincidan con la query
  - El resultado es una lista o diccionario vacío

### Ejemplos de Uso

```python
from google.cloud import firestore
from datetime import datetime, timezone

client = firestore.Client(project="trust-481601", database="socialnetworks")

# Consultar jobs pendientes
jobs = client.collection("pending_jobs").where("status", "==", "pending").stream()

# Consultar jobs fallidos
failed_jobs = client.collection("pending_jobs").where("status", "==", "failed").stream()

# Consultar jobs con resultado vacío
empty_jobs = client.collection("pending_jobs").where("status", "==", "empty_result").stream()

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
| `noreplies` | `done` | Job completado exitosamente |
| `noreplies` | `skipped` | `max_replies <= 0` y `replies_count <= 0` |

### Transiciones de `pending_jobs`

| Desde | Hacia | Condición |
|-------|-------|-----------|
| `pending` | `processing` | Inicio de verificación del job |
| `processing` | `done` | Job completado exitosamente con resultados no vacíos |
| `processing` | `failed` | Information Tracer reporta fallo, error al obtener resultados, o excepción |
| `processing` | `empty_result` | Job completado pero resultado vacío |
| `processing` | `pending` | Job con timeout o status desconocido (se reintenta) |

---

## Notas Importantes

1. **Sincronización**: Cuando un job en `pending_jobs` cambia a `done`, el post asociado en `posts` también cambia a `done`.

2. **Índices**: Para consultas eficientes, se requieren índices compuestos:
   - `posts`: `status + platform + created_at`
   - `pending_jobs`: `status + created_at`, `status + updated_at`

3. **Timestamps**: Todos los cambios de estado actualizan automáticamente el campo `updated_at` con la fecha/hora UTC actual.

4. **Consulta de Jobs Fallidos**: Para analizar jobs fallidos, se puede consultar tanto `status="failed"` como `status="empty_result"` para obtener una vista completa de los problemas.

