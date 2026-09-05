# EO-GE Validator (S-A.8)

## Propósito

Validar productos normalizados (contrato V1.0) y clasificarlos como
`AVAILABLE`, `PARTIAL` o `INVALID`, sin modificar la entrada.

## Niveles de validación

1. **Contrato** (`contract_schema`): JSON Schema `contracts/eo_ge_normalized_data.schema.json`
   vía `jsonschema`.
2. **Científico/semántico**: reglas que el schema no puede garantizar
   (identity, temporal, spatial, raster, quality, provenance) + reglas
   específicas de producto (Sentinel-2).

## Reglas

- **Identity:** `identity.id` presente.
- **Temporal:** datetime ISO-8601 válido; `start_time ≤ end_time`.
- **Spatial:** CRS con formato `EPSG:xxxx`; bbox coherente (oeste<este, sur<norte);
  resolución positiva; EPSG en rango.
- **Raster:** `data.kind == raster`; bandas presentes; unidades no vacías.
- **Quality:** cloud cover ∈ [0, 100].
- **Provenance:** `provider` y `original_product` presentes; checksum (si existe).
- **Sentinel-2:** plataforma Sentinel-2, instrumento MSI, nivel L2A, tile MGRS,
  coherencia CRS-tile, bandas estándar (B01–B12, B8A).

## AVAILABLE / PARTIAL / INVALID

- **AVAILABLE:** contrato válido, sin problemas científicos relevantes.
- **PARTIAL:** estructuralmente válido pero falta metadata no crítica
  (checksum ausente, algunas unidades, QA incompleto).
- **INVALID:** problema que impide confiar en el producto (schema inválido,
  datetime/CRS/resolución inválidos, cloud cover fuera de rango, identity
  inconsistente, bbox imposible, provenance insuficiente).

No se convierte PARTIAL en INVALID por ausencia de datos opcionales.

## Errores vs warnings

Los errores → `INVALID`; los warnings → `PARTIAL`. Cada error/warning lleva un
código determinista (p. ej. `SCHEMA_INVALID`, `DATETIME_INVALID`,
`CRS_INVALID`, `RESOLUTION_INVALID`, `CLOUD_COVER_OUT_OF_RANGE`,
`IDENTITY_MISSING`, `PROVENANCE_INCOMPLETE`, `CHECKSUM_MISSING`,
`S2_CRS_TILE_MISMATCH`), un campo y un mensaje.

## Sentinel-2

`Sentinel2Validator` añade las reglas específicas (plataforma/instrumento/nivel/
tile/CRS-tile/bandas). El validador base es reutilizable para Sentinel-1,
Landsat, MODIS, ERA5-Land, INEGI, etc.

## Inmutabilidad

`validate(data)` es una operación pura: no modifica `data` (verificado por test).

## Limitaciones

- No normaliza, no corrige, no descarga, no reproyecta, no crea COG/NetCDF/Zarr.
- La validación de `format: date-time` depende del `format_checker`.
- No valida el contenido de los arrays (solo la metadata del contrato).
