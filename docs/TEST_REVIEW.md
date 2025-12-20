# Revisión de Tests - GitHub Actions

## Resumen de la Implementación

Se ha creado un conjunto completo de tests con pytest que está configurado para funcionar correctamente en GitHub Actions.

## Estructura de Tests

### Directorios
- `tests/` - Tests nuevos con pytest (estructura completa)
- `test/` - Tests existentes (mantenidos para compatibilidad)

### Archivos de Test Creados

1. **`tests/conftest.py`** - Fixtures compartidas
   - `client`: Cliente de prueba FastAPI
   - `mock_stanza_doc`: Mock de Document de Stanza
   - `sample_article*`: Datos de ejemplo
   - `mock_env_vars`: Configuración de variables de entorno (incluye `STANZA_SKIP_INIT=1`)

2. **`tests/test_main.py`** - Tests para endpoints básicos
   - Root endpoint (`/`)
   - Health check (`/health`)
   - Documentación (`/docs`)
   - OpenAPI schema

3. **`tests/test_endpoints.py`** - Tests para endpoints de análisis
   - Análisis exitoso
   - Servicio no inicializado (503)
   - Input inválido (422)
   - Combinación de título y cuerpo

4. **`tests/test_models.py`** - Tests para modelos Pydantic
   - Validación de `ArticleInput`
   - Validación de `Metric` (flag, score, campos requeridos)

5. **`tests/test_metrics.py`** - Tests para funciones de métricas
   - `get_adjective_count`: Con y sin API key, fallback
   - `get_word_count`: Alto, medio, bajo
   - `get_sentence_complexity`: Óptimo, corto, largo
   - `get_verb_tense_analysis`: Óptimo, bajo, alto

6. **`tests/test_stanza_service.py`** - Tests para StanzaService
   - Inicialización
   - Creación de documentos
   - Propiedad `is_initialized`
   - Uso de variables de entorno

## Configuración para GitHub Actions

### Variables de Entorno en CI

El workflow (`/.github/workflows/test.yml`) configura:
- `STANZA_SKIP_INIT=1`: Evita descargar modelos de Stanza (grandes)
- `STANZA_LANG=es`: Idioma por defecto
- `STANZA_RESOURCES_DIR=/tmp/stanza_resources`: Directorio temporal
- `OPENROUTER_API_KEY`: No se configura (prueba comportamiento fallback)

### Optimizaciones para CI

1. **Sin descarga de modelos**: Los tests usan mocks, no requieren modelos reales
2. **Cache de dependencias**: Poetry cache para acelerar builds
3. **Matrix testing**: Configurado para Python 3.12
4. **Coverage reporting**: Genera reportes XML y HTML

## Verificaciones Realizadas

### ✅ Compatibilidad con GitHub Actions

- [x] Tests no requieren descarga de modelos Stanza (usando `STANZA_SKIP_INIT`)
- [x] Todos los tests usan mocks apropiados
- [x] Variables de entorno configuradas correctamente
- [x] Dependencias instaladas con Poetry
- [x] Coverage report configurado

### ✅ Estructura de Tests

- [x] Tests organizados por módulo
- [x] Fixtures compartidas en `conftest.py`
- [x] Tests independientes (no dependen entre sí)
- [x] Mocks apropiados para servicios externos

### ✅ Cobertura

- [x] Tests para endpoints principales
- [x] Tests para modelos
- [x] Tests para servicios
- [x] Tests para casos edge (errores, valores límite)

## Posibles Problemas y Soluciones

### Problema: Descarga de modelos Stanza
**Solución**: `STANZA_SKIP_INIT=1` evita la inicialización en tests

### Problema: Tests lentos
**Solución**: Uso de mocks evita llamadas reales a APIs

### Problema: Dependencias faltantes
**Solución**: Poetry maneja todas las dependencias automáticamente

### Problema: Coverage no se genera
**Solución**: Configurado en `pyproject.toml` y workflow

## Ejecución Local

```bash
# Instalar dependencias
poetry install

# Ejecutar todos los tests
poetry run pytest

# Con cobertura
poetry run pytest --cov=src/trust_api --cov-report=html

# Un archivo específico
poetry run pytest tests/test_main.py
```

## Ejecución en GitHub Actions

El workflow se ejecuta automáticamente en:
- Push a `main` o `develop`
- Pull requests a `main` o `develop`
- Manualmente via `workflow_dispatch`

## Próximos Pasos Recomendados

1. ✅ Tests básicos implementados
2. ⏳ Agregar tests de integración (opcional)
3. ⏳ Agregar tests de performance (opcional)
4. ⏳ Configurar Codecov para tracking de cobertura (opcional)

