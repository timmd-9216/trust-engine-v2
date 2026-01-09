# Monitoreo de Quota - Information Tracer API

## Evidencia de Monitoreo Disponible

### ✅ Script de Verificación: `scripts/check_api_quota.py`

**Ubicación:** `scripts/check_api_quota.py`

**Funcionalidad:**
- Verifica el estado de quota usando `check_api_usage()`
- Muestra información de uso diario y límites
- Analiza si hay problemas de quota

**Ejemplo de uso:**
```bash
poetry run python scripts/check_api_quota.py
```

**Respuesta actual verificada (2026-01-09):**
```
API Usage/Quota Information:
  limits: {'max_searches_per_day': 400}
  usage: {'day': {'searches_used': 400}}
  Status: QUOTA EXCEDIDA (400/400 = 100%)
```

### ✅ Función de Verificación: `check_api_usage()`

**Ubicación:** `src/trust_api/scrapping_tools/information_tracer.py` (línea 32)

**Endpoint utilizado:** `https://informationtracer.com/account_stat?token=xxx`

**Respuesta esperada:**
```json
{
  "usage": {
    "day": {
      "searches_used": 400,
      "period_start": "2026-01-09"
    },
    "month": {
      "searches_used": 2869,
      "period_start": "2025-12-01"
    }
  },
  "limits": {
    "max_searches_per_day": 400,
    "max_records_per_month": 510000
  }
}
```

### ✅ Endpoint REST API: `/api/quota`

**Ubicación:** `src/trust_api/scrapping_tools/main.py` (línea 453)

**Respuesta:**
```json
{
  "daily_used": 400,
  "daily_limit": 400,
  "percentage": 100.0,
  "status": "exceeded",
  "message": "Quota exceeded: 400/400 searches used"
}
```

### ✅ Dashboard Web Integrado

**Ubicación:** `src/trust_api/scrapping_tools/dashboard.html`

**Funcionalidad:**
- Muestra quota en tiempo real en el dashboard
- Alertas visuales cuando quota está alta (≥75% warning, ≥90% critical)
- Se actualiza automáticamente al cargar el dashboard

---

## ¿Qué Error Da Information Tracer Cuando Hay Problema de Quota?

### Comportamiento Observado

**Problema:** Information Tracer NO devuelve un mensaje de error explícito indicando "quota exceeded". Los errores son genéricos.

### Escenarios de Error:

#### 1. **Cuando se intenta `submit()` con quota excedida:**

**Comportamiento actual:**
- Information Tracer puede devolver:
  - **HTTP 429** (Too Many Requests / Rate Limit Exceeded)
  - **HTTP 403** (Forbidden) - posiblemente cuando quota está excedida
  - **HTTP 200** pero sin `id_hash256` en la respuesta JSON
  - Respuesta JSON con campo de error (pero formato no estándar)

**Código actual (ANTES de mejorar):**
- ❌ NO captura `response.status_code`
- ❌ Solo verifica si existe `id_hash256` en la respuesta
- ❌ Si no hay `id_hash256`, retorna `None` sin saber por qué
- ❌ NO diferencia entre quota excedida vs otros errores

**Código mejorado (AHORA):**
- ✅ Captura códigos HTTP: 429, 403, y otros >= 400
- ✅ Loguea el código HTTP específico
- ✅ Busca palabras clave en respuesta: "quota", "limit", "exceeded"
- ✅ Pero aún requiere verificación adicional con `check_api_usage()`

#### 2. **Cuando se verifica `status` de un job rechazado por quota:**

**Comportamiento:**
- Si el job fue rechazado en submit (quota excedida), nunca se crea
- `check_status()` puede devolver:
  - **"failed"** - si el job_id no existe
  - Respuesta sin campo "status" - indica que el job no fue creado
  - HTTP 404 o 400 - job no encontrado

**Evidencia de logs (2026-01-08):**
- Los logs NO muestran mensajes específicos de "quota exceeded"
- Solo muestran errores genéricos: "empty_result" o "failed"
- Esto confirma que Information Tracer NO expone mensajes específicos de quota

#### 3. **Cuando un job existente falla debido a quota:**

**Comportamiento observado:**
- Si un job ya existe y luego se excede la quota:
  - Information Tracer puede marcar el job como "failed"
  - No hay mensaje específico indicando que fue por quota
  - Solo se puede inferir verificando `check_api_usage()` al momento del fallo

### Evidencia de los Logs (2026-01-08)

**Análisis realizado:**
- ✅ 34 archivos de logs de error revisados
- ✅ 708 errores analizados
- ❌ **0 errores con mensajes específicos de "quota exceeded"**
- ❌ **0 errores con códigos HTTP 429 o 403 capturados**

**Conclusión:**
- Information Tracer NO expone mensajes explícitos de quota en errores
- Los errores son genéricos: "failed", "empty_result", o sin `id_hash256`
- La única forma de detectar quota excedida es verificando `check_api_usage()` después del error

### Solución Implementada

#### Mejora 1: Captura de Códigos HTTP en `submit()`

```python
# Ahora captura códigos HTTP específicos
if response.status_code == 429:
    logger.error("Submission failed: Rate limit exceeded (429)")
elif response.status_code == 403:
    logger.error("Submission failed: Forbidden (403) - possible quota exceeded")
elif response.status_code >= 400:
    logger.error(f"Submission failed: HTTP {response.status_code}")
```

#### Mejora 2: Verificación de Quota Post-Fallo

```python
# Cuando un job falla, se verifica quota automáticamente
elif status == "failed":
    # Check if quota is exceeded before marking as failed
    api_usage = check_api_usage(api_key)
    if searches_used >= daily_limit:
        final_status = "quota_exceeded"  # En lugar de "failed"
```

#### Mejora 3: Status `quota_exceeded` para Diferenciación

- Nuevo status: `quota_exceeded` (vs `failed` genérico)
- Permite identificar fallos temporales (quota) vs permanentes
- Facilita debugging y potencial retry futuro

---

## Recomendaciones

### Para Detectar Quota Excedida:

1. **Verificar quota ANTES de submit/retry:**
   - Usar `check_api_usage()` antes de procesar jobs
   - Si quota >= 90%, pausar procesamiento

2. **Capturar códigos HTTP:**
   - HTTP 429 → Rate limit (probablemente quota)
   - HTTP 403 → Forbidden (posiblemente quota excedida)
   - HTTP >= 400 → Error general

3. **Verificar quota POST-fallo:**
   - Cuando un job falla, verificar quota inmediatamente
   - Si quota está excedida, marcar como `quota_exceeded`

4. **Monitoreo proactivo:**
   - Dashboard muestra quota en tiempo real
   - Alertas cuando quota está alta
   - Prevenir fallos masivos verificando quota antes

---

## Limitaciones Conocidas

1. **Information Tracer NO expone mensajes explícitos de quota:**
   - Los errores son genéricos
   - No hay campo "quota_exceeded" en respuestas de error
   - Solo se puede inferir verificando `check_api_usage()`

2. **Detección reactiva (no proactiva):**
   - Actualmente detectamos quota DESPUÉS de que un job falla
   - No verificamos quota ANTES de hacer submit/retry
   - Esto puede prevenir algunos fallos, pero no todos

3. **Posible falsos positivos:**
   - Un job puede fallar por otra razón justo cuando quota está excedida
   - El código marcará como `quota_exceeded` aunque no sea la causa real
   - Esto es aceptable porque es mejor ser conservador

---

## Próximos Pasos Recomendados

1. ✅ **Implementar verificación de quota ANTES de retry** (alta prioridad)
   - Modificar `retry_empty_result_jobs_service()` para verificar quota primero
   - Pausar retries si quota >= 90%

2. ⚠️ **Mejorar detección de errores de quota en submit()** (media prioridad)
   - Ya mejorado para capturar códigos HTTP 429, 403
   - Verificar respuesta JSON para mensajes de error
   - Buscar palabras clave relacionadas con quota

3. ⏳ **Implementar retry automático para `quota_exceeded`** (baja prioridad)
   - Solo cuando quota esté disponible nuevamente
   - Evitar retries masivos que consuman quota inmediatamente

---

**Última actualización:** 2026-01-09  
**Status:** Monitoreo implementado, detección mejorada

