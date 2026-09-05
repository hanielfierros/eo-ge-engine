# Sentinel-2 L2A Normalizer

## Propósito

Transformar la `SourceRepresentation` producida por `Sentinel2L2AConnector` en
un objeto compatible con el contrato **EO-GE NORMALIZED DATA CONTRACT V1.0**.

## Entrada

`SourceRepresentation` (dict/dataclass de `app.connectors.base`) con: source,
product, source_id, source_metadata (STAC Item), acquisition, spatial, temporal,
resource, checksum, provenance y collection_metadata (item_assets de la
colección, con `data_type`, `raster:scale`, `raster:offset`, `nodata`).

## Salida

Diccionario conforme al JSON Schema `contracts/eo_ge_normalized_data.schema.json`
(contrato V1.0 FROZEN).

## Mapping

| Contrato | Fuente |
|---|---|
| `identity.id` | determinista `SENTINEL2_{product}_{datetime}_{tile}_v1` |
| `data_class` | `SCIENTIFIC_PRODUCT` |
| `source` | provider ESA, platform/instrument/collection del STAC Item |
| `product` | `product:type` (S2MSI2A), nivel `L2A` |
| `acquisition` | `start_datetime`/`end_datetime`/`datetime` del STAC |
| `spatial.crs/epsg` | `proj:epsg` o derivado del tile MGRS (p. ej. T12RYP → 32612) |
| `data.raster.bands` | assets espectrales (B01–B12, B8A) + metadata de item_assets |
| `quality.dataset_quality` | `eo:cloud_cover` |
| `provenance` | provider, source_id, retrieval_time, checksum, license |

## Reglas de conservación científica

- Normalizar NO simplifica: se conserva toda la metadata disponible.
- No se inventan valores/unidades/CRS/resolución/QA/incertidumbre/nodata.
- Un dato ausente se representa como ausente (clave podada), no como `null` ni
  valor supuesto.
- `dtype` se toma de `item_assets.data_type`; si falta, falla explícitamente.

## Manejo de datos ausentes

Las claves opcionales con valor `None` se eliminan (`_prune_nulls`) para cumplir
`additionalProperties: false`. Si falta CRS o bounds (obligatorios), el
normalizador falla explícitamente con `NormalizationError`.

## Determinismo

Mismo `SourceRepresentation` → mismo resultado (el `processing_time` de
provenance es el único campo con timestamp actual; el resto es determinista).

## Errores

`NormalizationError` para: producto incompatible, sin bandas espectrales,
banda sin dtype, CRS no determinable, bounds ausente, o salida incompatible
con el contrato.

## Validación

`normalize_validated()` comprueba la salida contra el JSON Schema V1.0. No
sustituye al validador científico de S-A.8.

## Limitaciones actuales

- No descarga datos ni crea COG/NetCDF/Zarr (eso es del Data Store).
- `storage.format = "COG"` es una declaración de formato canónico (S-A.2); la
  materialización real ocurre en S-A.9.
- No calcula NDVI ni índices.
