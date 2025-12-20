# Tests

Este directorio contiene los tests unitarios e integración para la API de Trust Engine.

## Estructura

```
tests/
├── __init__.py
├── conftest.py          # Fixtures compartidas y configuración
├── test_main.py         # Tests para main.py (endpoints básicos)
├── test_endpoints.py    # Tests para endpoints de análisis
├── test_models.py       # Tests para modelos Pydantic
├── test_metrics.py      # Tests para funciones de métricas
└── test_stanza_service.py  # Tests para StanzaService
```

## Ejecutar Tests

### Ejecutar todos los tests
```bash
poetry run pytest
```

### Ejecutar tests con cobertura
```bash
poetry run pytest --cov=src/trust_api --cov-report=html
```

### Ejecutar un archivo específico
```bash
poetry run pytest tests/test_main.py
```

### Ejecutar un test específico
```bash
poetry run pytest tests/test_main.py::test_root_endpoint
```

### Ejecutar tests en modo verbose
```bash
poetry run pytest -v
```

## Fixtures Disponibles

Las fixtures están definidas en `conftest.py`:

- `client`: Cliente de prueba para FastAPI
- `mock_stanza_service`: Mock del StanzaService
- `mock_stanza_doc`: Mock de un Document de Stanza
- `sample_article`: Artículo de ejemplo para testing
- `sample_article_long`: Artículo largo para tests de word count
- `sample_article_short`: Artículo corto para tests
- `mock_env_vars`: Mock de variables de entorno
- `mock_openrouter_api_key`: Mock de API key de OpenRouter
- `mock_openrouter_response`: Mock de respuesta de OpenRouter

## Cobertura

El proyecto está configurado para generar reportes de cobertura. Después de ejecutar los tests, puedes ver el reporte HTML en `htmlcov/index.html`.

## Notas

- Los tests usan mocks para evitar llamadas reales a APIs externas (OpenRouter, Stanza)
- Los tests de métricas verifican los diferentes umbrales y casos edge
- Los tests de endpoints verifican tanto casos exitosos como errores

