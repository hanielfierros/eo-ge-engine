# S-A.9 — Data Store — Reporte

## Estado

**READY_FOR_REVIEW** (Local Data Store implementado y validado offline).

## Archivos creados/modificados

- Creados: `app/storage/__init__.py`, `app/storage/base.py`,
  `app/storage/local.py`, `tests/test_local_data_store.py`,
  `docs/EO_GE_DATA_STORE.md`, `reports/S_A9_DATA_STORE_REPORT.md`.
- Modificados: `.gitignore` (añadido `storage/`), memoria.

## Arquitectura implementada

`LocalDataStore` (filesystem) con separación `source_cache/`, `normalized/`,
`derived/`, `.staging/`. Interfaz `DataStore`: put_metadata, get_metadata,
exists, delete, put_file, get_file, verify.

## Pruebas

`python -m unittest discover -s tests -p "test*.py"` → **96 passed / 0 failed**
(24 contrato + 16 conector + 18 normalizador + 21 validador + 17 data store).

## Integridad

SHA-256 por archivo; `verify()` detecta modificación/eliminación/tamaño
incorrecto/checksum distinto. Metadata persistida re-validada contra JSON Schema.

## Atomicidad

Escritura temporal + atomic rename; `put_metadata` falla sin corrupción
(verificado con mock de `os.replace`); `cleanup_staging()`.

## Recuperación

`cleanup_staging()` elimina staging incompleto; un producto en staging no
aparece como comprometido.

## Limitaciones

- Backend local; sin PostGIS/Zarr/cloud.
- No materializa COG ni convierte formatos.
- No descarga datos.

## Decisiones nuevas

- `deterministic_id` como identidad primaria; duplicado idempotente, conflicto → `StorageConflictError`.
- Metadata persistida re-validada contra el contrato; INVALID rechazado, PARTIAL almacenado.
- Path safety estricto (rechazo de `../`, absolutas, drive, vacías).
- Estados de almacenamiento (STAGED/COMMITTED/FAILED) separados de `quality.status`.

## Datasets descargados

**NO**.

## Radar Engine

**NO modificado**.

## S-A.10

**NO iniciada**.
