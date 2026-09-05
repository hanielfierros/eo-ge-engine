# EO-GE Data Store (S-A.9)

## Arquitectura

```
storage/
├── source_cache/   # datos originales del proveedor (JP2/ZIP/metadata)
├── normalized/     # productos validados bajo contrato V1.0
├── derived/        # productos derivados futuros (NDVI, indices, ...)
└── .staging/       # escrituras en curso (atomicidad)
```

## Separación source / normalized / derived

- `source_cache/`: datos originales, sin modificación científica.
- `normalized/`: metadata normalizada + archivos científicos validados.
- `derived/`: reservado para derivados (NO se genera en S-A.9).

## Metadata

`normalized/<deterministic_id>/metadata.json` — la representación normalizada
completa (tal cual la produce el Normalizer). Se re-valida contra el JSON Schema
al persistir; los productos INVALID (estructuralmente inválidos) se rechazan;
los PARTIAL (válidos pero con metadata opcional ausente) se almacenan.

## Archivos

`normalized/<deterministic_id>/files/<relative_path>` + `manifest.json` con
`{files: {relative_path: {filename, relative_path, media_type, size, sha256,
role, format, source_generated}}}`.

## SHA-256

Cada archivo se verifica por existencia, tamaño y SHA-256. `verify()` devuelve
`False` ante modificación/eliminación/tamaño incorrecto/checksum distinto.

## Atomicidad

`write temporal → atomic rename` dentro de `normalized/`. Nunca queda
`metadata.json` parcial; ante fallo se elimina el staging y se conserva el estado
previo.

## Deterministic IDs

El `deterministic_id` es la identidad primaria. Guardar de nuevo el mismo
producto: idempotente si el contenido es igual; `StorageConflictError` si es
distinto. No se sobrescribe silenciosamente.

## Estados

- `STAGED`: escritura en curso (`.staging/`).
- `COMMITTED`: producto persistido y verificado.
- `FAILED`: error (staging limpiado).

Los estados de almacenamiento son independientes del `quality.status`
(AVAILABLE/PARTIAL/INVALID) del contrato.

## Recuperación

`cleanup_staging()` elimina escrituras interrumpidas. Un producto en staging no
aparece como comprometido.

## Path safety

`validate_id()` y `validate_relative_path()` rechazan `../`, rutas absolutas,
letras de unidad y rutas vacías, confinando todo a `storage/`.

## Limitaciones

- Backend local (filesystem); sin PostGIS/Zarr/cloud.
- No materializa COG ni convierte formatos.
- No descarga datos.

## Evolución futura

El backend puede sustituirse (p. ej. object storage / Zarr / PostGIS) sin
modificar Connector/Normalizer/Validator, manteniendo la interfaz `DataStore`.
