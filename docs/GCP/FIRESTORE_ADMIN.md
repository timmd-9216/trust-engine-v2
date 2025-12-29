# Administración de Firestore

Este documento describe las tareas de administración de Firestore para el proyecto.

## Configuración

- **Proyecto**: `trust-481601`
- **Base de datos**: `socialnetworks`
- **Colección principal**: `posts`

## Índices

Firestore requiere índices compuestos para queries que combinan filtros y ordenamiento en diferentes campos.

### Índice requerido: status + created_at

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
| `max_replies` | number | Máximo de respuestas a recolectar (no indexado) |
| `status` | string | Estado: `noreplies`, `done`, `skipped` |
| `updated_at` | timestamp | Última actualización del documento |

### Lógica de determinación del máximo de respuestas a buscar

Al procesar posts con el endpoint `/process-posts`, el sistema determina cuántas respuestas buscar de Information Tracer usando la siguiente prioridad:

1. **`max_replies`** (prioridad más alta): Si este campo existe y es mayor a 0, se usa como límite máximo.
2. **`replies_count`** (fallback): Si `max_replies` no está disponible o es inválido, se usa `replies_count` si existe y es mayor a 0.
3. **Valor por defecto**: Si ninguno de los campos anteriores está disponible o es válido, se usa 100 como límite por defecto.

**Ejemplo:**
- Si `max_replies=50` y `replies_count=200`, se buscarán máximo 50 respuestas (usa `max_replies`).
- Si `max_replies` no existe y `replies_count=200`, se buscarán máximo 200 respuestas (usa `replies_count`).
- Si ambos campos son `null` o `<= 0`, se buscarán máximo 100 respuestas (valor por defecto).

**Nota:** Si ambos campos (`max_replies` y `replies_count`) son `null` o `<= 0`, el post se marca como `skipped` y no se procesa.

## Estados de los posts

| Estado | Descripción |
|--------|-------------|
| `noreplies` | Post pendiente de procesar |
| `done` | Post procesado exitosamente, respuestas guardadas en GCS |
| `skipped` | Post saltado porque `max_replies <= 0` |

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

