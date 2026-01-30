# Administración de Firestore

Este documento describe las tareas de administración de Firestore para el proyecto.

## Configuración

- **Proyecto**: `trust-481601`
- **Base de datos**: `socialnetworks`
- **Colección principal**: `posts`

## Índices

Firestore requiere índices compuestos para queries que combinan filtros y ordenamiento en diferentes campos.

### Índices requeridos

#### Índice: posts - status + created_at

Este índice es necesario para la query que obtiene posts con `status='noreplies'` ordenados por `created_at`:

```bash
gcloud firestore indexes composite create \
  --project=trust-481601 \
  --database=socialnetworks \
  --collection-group=posts \
  --query-scope=COLLECTION \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=ASCENDING
```

#### Índice: pending_jobs - status + created_at

Este índice es necesario para la query que obtiene jobs pendientes con `status='pending'` ordenados por `created_at`:

```bash
gcloud firestore indexes composite create \
  --project=trust-481601 \
  --database=socialnetworks \
  --collection-group=pending_jobs \
  --query-scope=COLLECTION \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=ASCENDING
```

### Listar índices existentes

```bash
gcloud firestore indexes composite list \
  --project=trust-481601 \
  --database=socialnetworks
```

### Eliminar un índice

```bash
# Primero lista los índices para obtener el ID
gcloud firestore indexes composite list \
  --project=trust-481601 \
  --database=socialnetworks

# Luego elimina por ID
gcloud firestore indexes composite delete INDEX_ID \
  --project=trust-481601 \
  --database=socialnetworks
```

## Consultas útiles

### Ver documentos de una colección

```bash
# Usando Firebase CLI (requiere firebase-tools instalado)
firebase firestore:get posts --project=trust-481601

# O usar la consola web:
# https://console.firebase.google.com/project/trust-481601/firestore/databases/socialnetworks/data/posts
```

### Consultar posts por status

Desde Python:

```python
from google.cloud import firestore

client = firestore.Client(project="trust-481601", database="socialnetworks")

# Posts sin respuestas
posts = client.collection("posts").where("status", "==", "noreplies").stream()
for doc in posts:
    print(doc.id, doc.to_dict())

# Posts procesados
posts = client.collection("posts").where("status", "==", "done").stream()

# Posts saltados
posts = client.collection("posts").where("status", "==", "skipped").stream()
```

### Contar documentos por status

```python
from google.cloud import firestore

client = firestore.Client(project="trust-481601", database="socialnetworks")

statuses = ["noreplies", "done", "skipped"]
for status in statuses:
    count = len(list(client.collection("posts").where("status", "==", status).stream()))
    print(f"{status}: {count}")
```

## Campos de la colección `posts`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `post_id` | string | ID único del post en la red social |
| `platform` | string | Plataforma (instagram, twitter, facebook, etc.) |
| `country` | string | País |
| `candidate_id` | string | ID del candidato |
| `created_at` | timestamp | Fecha de creación del post |
| `replies_count` | number | Número de respuestas del post (no indexado) |
| `max_posts_replies` | number | Máximo de respuestas a recolectar (no indexado). Se acepta también `max_replies` por compatibilidad. |
| `status` | string | Estado: `noreplies`, `done`, `skipped` |
| `updated_at` | timestamp | Última actualización del documento |

### Lógica de determinación del máximo de respuestas a buscar

Al procesar posts con el endpoint `/process-posts`, el sistema determina cuántas respuestas buscar de Information Tracer usando la siguiente prioridad:

1. **`max_posts_replies`** (prioridad más alta; se acepta también `max_replies` por compatibilidad): Si existe y es mayor a 0, se usa como límite máximo.
2. **`replies_count`** (fallback): Si `max_posts_replies` no está disponible o es inválido, se usa `replies_count` si existe y es mayor a 0.
3. **Valor por defecto**: Si ninguno de los campos anteriores está disponible o es válido, se usa 100 como límite por defecto.

**Ejemplo:**
- Si `max_posts_replies=50` y `replies_count=200`, se buscarán máximo 50 respuestas (usa `max_posts_replies`).
- Si `max_posts_replies` no existe y `replies_count=200`, se buscarán máximo 200 respuestas (usa `replies_count`).
- Si ambos campos son `null` o `<= 0`, se buscarán máximo 100 respuestas (valor por defecto).

**Nota:** Si ambos campos (`max_posts_replies` y `replies_count`) son `null` o `<= 0`, el post se marca como `skipped` y no se procesa.

## Campos de la colección `pending_jobs`

La colección `pending_jobs` almacena los jobs de Information Tracer que están siendo procesados.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `job_id` | string | ID del job en Information Tracer (hash_id/id_hash256) |
| `post_doc_id` | string | ID del documento Firestore en la colección `posts` |
| `post_id` | string | ID del post en la plataforma externa (Twitter, Facebook, etc.) |
| `platform` | string | Plataforma (twitter, facebook, instagram, etc.) |
| `country` | string | País |
| `candidate_id` | string | ID del candidato |
| `max_posts_replies` | number | Máximo de respuestas a recolectar (se acepta también `max_posts` por compatibilidad) |
| `sort_by` | string | Ordenamiento: `"time"` o `"engagement"` |
| `status` | string | Estado: `pending`, `processing`, `done`, `failed`, `empty_result`, `verified` |
| `retry_count` | number | Número de veces que se ha reintentado el job (se incrementa cuando se reprocesa un job ya procesado) |
| `created_at` | timestamp | Fecha de creación del job |
| `updated_at` | timestamp | Última actualización del job |

### Diferencia entre `post_doc_id` y `post_id`

Es importante entender la diferencia entre estos dos campos y a qué colección corresponde cada uno:

#### `post_doc_id`
- **Colección**: Este campo **solo existe** en la colección `pending_jobs` como referencia
- **Referencia**: Apunta al **ID del documento** en la colección `posts`
- **Tipo**: ID del documento Firestore
- **Ejemplo**: `"Wm2WxCNSt6ErumnELg7y"`
- **Propósito**: Identificador único del documento en la colección `posts` de Firestore. Se guarda en `pending_jobs` para poder actualizar el documento original del post cuando el job termine.
- **Uso**: Se utiliza para actualizar el documento del post en la colección `posts` (por ejemplo, cambiar su `status` a `"done"` usando `update_post_status(post_doc_id, "done")`)
- **Formato**: ID auto-generado por Firestore (cadena alfanumérica)

#### `post_id`
- **Colecciones**: Este campo existe en **ambas colecciones**:
  - En la colección `posts`: como un campo del documento (ID del post en la plataforma)
  - En la colección `pending_jobs`: como referencia al mismo ID del post
- **Tipo**: ID del post en la plataforma externa
- **Ejemplo**: `"1996509040751559080"`
- **Propósito**: Identificador del post en la red social original (Twitter, Facebook, Instagram, etc.)
- **Uso**: 
  - Se utiliza para construir la query a Information Tracer: `"reply:{post_id}"`
  - Se utiliza como nombre del archivo en GCS: `{country}/{platform}/{candidate_id}/{post_id}.json`
- **Formato**: ID numérico o alfanumérico según la plataforma (Twitter usa IDs numéricos largos)

**Ejemplo práctico:**

```python
# ===== COLECCIÓN 'posts' =====
# Documento con ID: "Wm2WxCNSt6ErumnELg7y"
# Campos del documento:
#   - post_id: "1996509040751559080"  # ID del post en Twitter
#   - platform: "twitter"
#   - country: "argentina"
#   - candidate_id: "candidate1"
#   - status: "noreplies"
#   - ...

# ===== AL CREAR UN JOB EN 'pending_jobs' =====
# Se guarda un nuevo documento en la colección 'pending_jobs' con:
save_pending_job(
    job_id="abc123...",
    post_doc_id="Wm2WxCNSt6ErumnELg7y",  # Referencia al documento en 'posts'
    post_id="1996509040751559080",       # Copia del post_id del documento en 'posts'
    platform="twitter",
    country="argentina",
    candidate_id="candidate1",
    ...
)

# Resultado: Nuevo documento en 'pending_jobs' con estos campos:
#   - job_id: "abc123..."
#   - post_doc_id: "Wm2WxCNSt6ErumnELg7y"  # Referencia a 'posts'
#   - post_id: "1996509040751559080"       # Copia del post_id
#   - platform: "twitter"
#   - status: "pending"
#   - ...

# ===== CUANDO EL JOB TERMINA =====
# 1. Se usa post_id (de 'pending_jobs') para construir la query: "reply:1996509040751559080"
# 2. Se usa post_id para el nombre del archivo: "argentina/twitter/candidate1/1996509040751559080.json"
# 3. Se usa post_doc_id para actualizar el documento en 'posts':
#    update_post_status("Wm2WxCNSt6ErumnELg7y", "done")
#    # Esto actualiza el documento "Wm2WxCNSt6ErumnELg7y" en la colección 'posts'

### Reintentos y Versiones Anteriores

Cuando un job se reprocesa (cambia de status "done" a "pending" y se procesa nuevamente), el sistema:

1. **Incrementa `retry_count`**: El campo `retry_count` en el documento del job se incrementa automáticamente
2. **Guarda metadata en el JSON**: El JSON guardado en GCS incluye un campo `_metadata` con información del reintento:
   ```json
   {
     "_metadata": {
       "is_retry": true,
       "retry_count": 2,
       "retry_timestamp": "2024-01-05T12:00:00Z",
       "previous_file_existed": true,
       "older_version": {
         // Versión completa del JSON anterior
       }
     },
     // ... datos actuales del resultado
   }
   ```
3. **Sobrescribe el archivo**: El archivo en GCS se sobrescribe con la nueva versión, pero la versión anterior se preserva dentro de `_metadata.older_version`

**Nota**: El campo `retry_count` solo se incrementa cuando se detecta que el archivo ya existe en GCS (indicando un reintento). Los jobs nuevos tienen `retry_count = 0` o el campo no existe.
```

## Estados

Para información detallada sobre todos los estados posibles y sus transiciones, consulta: [Estados de las Colecciones Firestore](../FIRESTORE_STATUS.md)

### Estados de los posts

| Estado | Descripción |
|--------|-------------|
| `noreplies` | Post pendiente de procesar |
| `done` | Post procesado exitosamente, respuestas guardadas en GCS |
| `skipped` | Post saltado porque `max_posts_replies <= 0` |

### Estados de los jobs

| Estado | Descripción |
|--------|-------------|
| `pending` | Job pendiente de procesar |
| `processing` | Job en proceso de verificación con Information Tracer |
| `done` | Job completado exitosamente, resultados guardados en GCS |
| `failed` | Job falló al procesar (error de API, excepción, etc.) |
| `empty_result` | Job completado pero el resultado está vacío |
| `verified` | Job verificado como resultado vacío esperado (twitter con replies_count <= 2) |

## Actualizar status de un documento

```python
from google.cloud import firestore
from datetime import datetime, timezone

client = firestore.Client(project="trust-481601", database="socialnetworks")

doc_ref = client.collection("posts").document("DOCUMENT_ID")
doc_ref.update({
    "status": "done",
    "updated_at": datetime.now(timezone.utc)
})
```

## Resetear posts para reprocesar

Si necesitas reprocesar posts que ya fueron procesados:

```python
from google.cloud import firestore
from datetime import datetime, timezone

client = firestore.Client(project="trust-481601", database="socialnetworks")

# Resetear todos los posts "done" a "noreplies"
posts = client.collection("posts").where("status", "==", "done").stream()
batch = client.batch()
count = 0

for doc in posts:
    batch.update(doc.reference, {
        "status": "noreplies",
        "updated_at": datetime.now(timezone.utc)
    })
    count += 1
    
    # Firestore batch limit is 500
    if count % 500 == 0:
        batch.commit()
        batch = client.batch()

if count % 500 != 0:
    batch.commit()

print(f"Reset {count} posts to 'noreplies'")
```

## Backup y Exportación

### Exportar colección a GCS

```bash
gcloud firestore export gs://trust-dev/firestore-backups/$(date +%Y-%m-%d) \
  --project=trust-481601 \
  --database=socialnetworks \
  --collection-ids=posts
```

### Importar desde backup

```bash
gcloud firestore import gs://trust-dev/firestore-backups/2025-01-01 \
  --project=trust-481601 \
  --database=socialnetworks
```

## Monitoreo

### Ver operaciones en curso

```bash
gcloud firestore operations list \
  --project=trust-481601 \
  --database=socialnetworks
```

### Ver uso de la base de datos

Accede a la consola de Firebase:
- https://console.firebase.google.com/project/trust-481601/firestore/databases/socialnetworks/usage

## Permisos

El service account `ci-deployer@trust-481601.iam.gserviceaccount.com` necesita los siguientes roles para acceder a Firestore:

- `roles/datastore.user` (lectura/escritura de documentos)

Para administrar índices:
- `roles/datastore.indexAdmin`

```bash
# Dar permisos de lectura/escritura
gcloud projects add-iam-policy-binding trust-481601 \
  --member="serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

# Dar permisos para administrar índices
gcloud projects add-iam-policy-binding trust-481601 \
  --member="serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com" \
  --role="roles/datastore.indexAdmin"
```

## Scripts útiles

### Script para crear todos los índices necesarios

Crea un archivo `scripts/create_firestore_indexes.sh`:

```bash
#!/bin/bash
# Script para crear índices de Firestore necesarios

PROJECT_ID="trust-481601"
DATABASE="socialnetworks"

echo "Creando índices de Firestore..."

# Índice: status + created_at (para query de posts sin respuestas ordenados por fecha)
gcloud firestore indexes composite create \
  --project="${PROJECT_ID}" \
  --database="${DATABASE}" \
  --collection-group=posts \
  --query-scope=COLLECTION \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=ASCENDING

echo "Índices creados exitosamente"
echo ""
echo "Verifica el estado de los índices:"
echo "  gcloud firestore indexes composite list --project=${PROJECT_ID} --database=${DATABASE}"
```

### Verificar conexión a Firestore

```python
#!/usr/bin/env python3
"""Script para verificar la conexión a Firestore."""

from google.cloud import firestore

def verify_firestore_connection():
    try:
        client = firestore.Client(project="trust-481601", database="socialnetworks")
        
        # Intentar leer un documento
        docs = list(client.collection("posts").limit(1).stream())
        
        print("✓ Conexión exitosa a Firestore")
        print(f"  Proyecto: trust-481601")
        print(f"  Base de datos: socialnetworks")
        print(f"  Documentos en 'posts': {len(docs)} (mostrando 1)")
        
        if docs:
            print(f"  Ejemplo de documento: {docs[0].id}")
            
    except Exception as e:
        print(f"✗ Error de conexión: {e}")

if __name__ == "__main__":
    verify_firestore_connection()
```

## Troubleshooting

### Error: "The query requires an index"

Si ves este error, necesitas crear el índice compuesto correspondiente. El mensaje de error incluye un enlace directo para crearlo en la consola de Firebase.

Alternativamente, usa el comando `gcloud firestore indexes composite create` como se muestra arriba.

### Error: "NOT_FOUND: Project or database does not exist"

Verifica que estás usando el nombre correcto de la base de datos (`socialnetworks`, no `(default)`).

### Error: "PERMISSION_DENIED"

Verifica que tu cuenta o service account tenga los permisos necesarios:

```bash
# Ver permisos actuales
gcloud projects get-iam-policy trust-481601 \
  --flatten="bindings[].members" \
  --filter="bindings.members:YOUR_EMAIL_OR_SA" \
  --format="table(bindings.role)"
```

### Los documentos no se actualizan

Verifica que el campo `_doc_id` esté presente en los documentos. Este campo se agrega automáticamente al consultar y es necesario para actualizar el documento.

