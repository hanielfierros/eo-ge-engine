# S-A.10 — Catalog — Reporte

## Estado

**READY_FOR_REVIEW** (Catalog implementado y validado offline).

## Archivos

- Creados: `app/catalog/__init__.py`, `app/catalog/catalog.py`,
  `app/catalog/adapter.py`, `tests/test_catalog.py`, `docs/EO_GE_CATALOG.md`,
  `reports/S_A10_CATALOG_REPORT.md`.
- Modificados: `.gitignore` (añadido `catalog/`), memoria.

## Esquema

Tablas `catalog_metadata`, `collections`, `items`, `assets` + índices; modelo
STAC-compatible. Item `id` = `deterministic_id`.

## Tests

`python -m unittest discover -s tests -p "test*.py"` → **114 passed / 0 failed**
(24 contrato + 16 conector + 18 normalizador + 21 validador + 17 data store + 18 catálogo).

## Búsquedas implementadas

collection, datetime (exacto y rango), platform, product, validation_status y
bbox (intersección en Python).

## Integración

`Sentinel2 fixture → Normalizer → Validator → LocalDataStore → metadata.json →
Catalog Adapter → SQLite → search() → Item → Asset → Data Store reference` funciona offline.

## Decisiones

- `deterministic_id` como identidad primaria del Item; registro idempotente; conflicto → `CATALOG_ID_CONFLICT`.
- Adapter deriva el Item desde el producto normalizado (sin metadata paralela).
- Item + Assets transaccional (rollback ante error).
- Path safety en `storage_path` y `href`.
- Búsqueda espacial MVP por bbox (sin PostGIS).

## Limitaciones

- SQLite local; sin PostGIS/STAC API/cloud.
- No almacena arrays raster en SQLite.

## Datasets descargados

**NO**.

## Radar Engine

**NO modificado**.

## S-A.11

**NO iniciada**.
