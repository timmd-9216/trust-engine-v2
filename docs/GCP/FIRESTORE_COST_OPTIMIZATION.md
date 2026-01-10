# Optimización de Costos de Firestore - Cloud Firestore Read Operations

## Problema Identificado

Los costos de "App Engine" en realidad son de **Cloud Firestore Read Operations**. 

### Contexto:
- Firestore cobra **$0.06 por cada 100,000 reads**
- Con 3 schedulers ejecutándose cada 30 minutos (48 veces/día cada uno = 144 ejecuciones/día)
- Si cada ejecución hace miles de reads, los costos se acumulan rápidamente

### Ejemplo de Costo:
```
144 ejecuciones/día × 10,000 reads/ejecución = 1,440,000 reads/día
1,440,000 reads/día × 30 días = 43,200,000 reads/mes
43,200,000 reads × $0.06 / 100,000 = $25.92/mes
```

## Problemas Encontrados en el Código

### 1. **Count Queries Sin Límite** (MUY COSTOSO) ❌

**Ubicación:** `src/trust_api/scrapping_tools/services.py`

**Problema:** Las funciones `count_jobs_by_status()` y `count_posts_by_status()` iteran sobre **TODOS** los documentos para contar:

```python
# ❌ PROBLEMA: Lee TODOS los documentos para contar
def count_jobs_by_status(status: str, ...):
    query = client.collection("pending_jobs").where("status", "==", status)
    count = 0
    for _ in query.stream():  # ⚠️ Lee TODOS los documentos!
        count += 1
    return count
```

**Impacto:** Si tienes 10,000 jobs con status='pending', esto genera 10,000 reads cada vez que se ejecuta.

**Cuándo se ejecuta:** Probablemente en cada ejecución del scheduler si hay endpoints que muestran conteos.

### 2. **Query de Posts Sin Límite Inicial** ⚠️

**Ubicación:** `process_posts_service()` línea 1330

**Problema:** Se hace query de todos los posts primero, luego se limita en Python:

```python
# ⚠️ PROBLEMA: Lee TODOS los posts primero
all_posts = query_posts_without_replies(max_posts=None)  # Sin límite!
if max_posts is not None:
    posts = all_posts[:max_posts]  # Limita después en Python
```

**Impacto:** Si hay miles de posts con status='noreplies', se leen todos aunque solo se procesen 10.

**Solución:** Agregar límite directamente en la query de Firestore.

### 3. **Frecuencia Alta de Schedulers** ⚠️

**Ubicación:** `terraform/cloud_scheduler_process_posts.tf`

**Problema:** Los schedulers se ejecutan cada 30 minutos:

```hcl
# process-posts-hourly: cada 30 minutos (0,30 * * * *)
# process-jobs-hourly: cada 30 minutos (15,45 * * * *)
# json-to-parquet-daily: una vez al día
```

**Impacto:** 96 ejecuciones/día del scheduler principal + 96 ejecuciones/día del segundo = 192 ejecuciones/día. Si cada una hace 10,000 reads = 1,920,000 reads/día.

## Soluciones Recomendadas

### Solución 1: Eliminar o Optimizar Count Queries (ALTA PRIORIDAD) ✅

**Opción A: Eliminar count queries si no son críticas**
```python
# Si el count solo se usa para logging/monitoreo, elimínalo
# o hazlo opcional con un flag
```

**Opción B: Usar Aggregate Queries (Firestore v9+)**
```python
# Firestore tiene agregaciones desde v9, pero requiere actualizar la biblioteca
# Si es posible, usar COUNT() agregado en lugar de iterar
```

**Opción C: Cachear conteos**
```python
# Guardar conteos en un documento separado y actualizarlos en batch
# o usar Cloud Functions triggers para mantener conteos actualizados
```

**Opción D: Limitar count queries**
```python
# Agregar límite máximo para evitar reads excesivos
def count_jobs_by_status(status: str, max_reads: int = 1000):
    query = client.collection("pending_jobs").where("status", "==", status).limit(max_reads)
    count = 0
    for _ in query.stream():
        count += 1
    # Si count == max_reads, probablemente hay más (usar aproximación)
    return count
```

### Solución 2: Agregar Límites Directamente en Queries (ALTA PRIORIDAD) ✅

**Modificar `query_posts_without_replies()`:**
```python
def query_posts_without_replies(max_posts: int | None = None) -> list[dict[str, Any]]:
    client = get_firestore_client()
    query = (
        client.collection(settings.firestore_collection)
        .where("status", "==", "noreplies")
        .where("platform", "!=", "twitter")  # Ya está filtrado
        .order_by("created_at")
    )
    
    # ✅ AGREGAR LÍMITE EN LA QUERY (no después en Python)
    if max_posts is not None and max_posts > 0:
        query = query.limit(max_posts)
    else:
        # ⚠️ Si no hay límite, usar un límite máximo por seguridad
        query = query.limit(1000)  # Límite máximo razonable
    
    posts = []
    for doc in query.stream():
        # ...
```

**Modificar `process_posts_service()`:**
```python
# ✅ Pasar el límite directamente a la query
all_posts = query_posts_without_replies(max_posts=max_posts or 100)  # Límite por defecto
# Ya no necesitas hacer [:max_posts] después
```

### Solución 3: Reducir Frecuencia de Schedulers (MEDIA PRIORIDAD) ✅

**Cambiar de cada 30 minutos a cada hora o cada 2 horas:**

```hcl
# En terraform/cloud_scheduler_process_posts.tf

# Opción A: Cada hora
variable "schedule" {
  default = "0 * * * *"  # Cada hora en minuto 0
}

variable "process_jobs_schedule" {
  default = "30 * * * *"  # Cada hora en minuto 30 (15 min después del primero)
}

# Opción B: Cada 2 horas
variable "schedule" {
  default = "0 */2 * * *"  # Cada 2 horas
}

variable "process_jobs_schedule" {
  default = "30 */2 * * *"  # Cada 2 horas, 30 min después
}
```

**Impacto:** Reduciría de 192 ejecuciones/día a 48 ejecuciones/día (75% menos reads).

### Solución 4: Agregar Límites en Todas las Queries (ALTA PRIORIDAD) ✅

**Asegurar que todas las queries tengan límites razonables:**

```python
# query_pending_jobs: Ya tiene límite ✅
def query_pending_jobs(max_jobs: int | None = None):
    if max_jobs is not None and max_jobs > 0:
        query = query.limit(max_jobs)
    else:
        query = query.limit(100)  # ✅ Límite por defecto

# query_done_jobs: Ya tiene límite ✅
# query_empty_result_jobs: Ya tiene límite ✅
# query_posts_without_replies: ⚠️ NECESITA LÍMITE POR DEFECTO
```

### Solución 5: Usar Paginación para Queries Grandes (BAJA PRIORIDAD) ⚠️

Si necesitas procesar muchos documentos, usar paginación en lugar de cargar todo:

```python
# En lugar de cargar todos los posts de una vez
# Usar paginación con start_after
def query_posts_without_replies_paginated(limit: int = 100, start_after_doc_id: str | None = None):
    query = client.collection("posts").where("status", "==", "noreplies").order_by("created_at")
    
    if start_after_doc_id:
        start_after_doc = client.collection("posts").document(start_after_doc_id).get()
        query = query.start_after([start_after_doc])
    
    query = query.limit(limit)
    # ...
```

## Plan de Implementación Recomendado

### Fase 1: Quick Wins (Implementar Ahora) 🚀

1. ✅ **Agregar límite por defecto en `query_posts_without_replies()`**
   - Agregar `.limit(100)` si no se especifica max_posts
   - Esto reducirá reads inmediatamente

2. ✅ **Modificar `process_posts_service()` para pasar límite directamente**
   - Cambiar `query_posts_without_replies(max_posts=None)` a `query_posts_without_replies(max_posts=max_posts or 100)`

3. ✅ **Eliminar o deshabilitar count queries si no son críticas**
   - Si solo se usan para logging, eliminarlas o hacerlas opcionales

### Fase 2: Optimizaciones Medias (Esta Semana) ⚡

4. ✅ **Reducir frecuencia de schedulers**
   - Cambiar de cada 30 minutos a cada hora
   - Reduciría ejecuciones a la mitad

5. ✅ **Agregar límites máximos en todas las queries**
   - Asegurar que ninguna query sin límite pueda leer más de 1000 documentos

### Fase 3: Optimizaciones Avanzadas (Opcional) 🔧

6. ⚠️ **Implementar cache de conteos**
   - Usar Cloud Functions triggers para mantener conteos actualizados
   - O usar un documento separado para almacenar conteos

7. ⚠️ **Implementar paginación para queries grandes**
   - Si realmente necesitas procesar miles de documentos

## Verificación de Impacto

### Antes de optimizar:
```
Ejecuciones/día: 192
Reads/ejecución: ~10,000 (sin límites)
Total reads/día: ~1,920,000
Costo/mes: ~$34.56
```

### Después de optimizar (Fase 1 + 2):
```
Ejecuciones/día: 96 (reducir frecuencia)
Reads/ejecución: ~500 (con límites)
Total reads/día: ~48,000
Costo/mes: ~$0.86
Ahorro: ~97% ✅
```

## Cómo Monitorear Reads de Firestore

### Ver uso de Firestore en la consola:
1. Ve a: https://console.cloud.google.com/firestore/usage?project=trust-481601
2. Selecciona "Read operations"
3. Filtra por fecha para ver tendencias

### Verificar costos en Billing:
1. Ve a: https://console.cloud.google.com/billing/reports?project=trust-481601
2. Filtra por servicio: "Cloud Firestore"
3. Filtra por SKU: "Firestore Read Operations"
4. Ver costos por día

## Nota sobre "App Engine" en Facturación

Aunque los costos aparecen bajo "App Engine", en realidad son de **Cloud Firestore Read Operations**. Esto sucede porque:

1. Cloud Firestore puede aparecer bajo diferentes categorías en reportes de billing
2. Los schedulers que invocan Cloud Run generan actividad que se categoriza bajo App Engine
3. Es normal que aparezca así - lo importante es verificar el SKU específico

Para ver el detalle correcto:
- Ve a Billing → Reports
- Filtra por SKU: "Firestore Read Operations" o "Cloud Firestore"
- Esto mostrará los costos reales de Firestore

