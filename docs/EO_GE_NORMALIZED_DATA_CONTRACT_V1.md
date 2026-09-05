# EO-GE NORMALIZED DATA CONTRACT V1.0

**Contrato canónico de datos normalizados** del **EARTH OBSERVATION & GEOSPATIAL
INTELLIGENCE ENGINE (EO-GE ENGINE)**.

- **VERSION:** 1.0
- **STATUS:** FROZEN
- **PROVEEDOR-AGNÓSTICO:** no depende de ninguna misión, proveedor ni formato físico.

---

## 1. Propósito

Establecer una interfaz estable y canónica entre la adquisición de observación
terrestre (Connectors) y su consumo (Normalizer, Validator, Data Store, Catalog,
GeoData Interface y el futuro Interpretation Engine). El contrato permite que un
dato sea interpretado sin conocer la fuente, el formato ni la implementación de
almacenamiento.

## 2. Alcance

Representa: observaciones satelitales, productos científicos, productos
derivados, reanálisis, modelos, datos raster, vectoriales y series temporales.
**No** es un contrato de imágenes de visualización.

## 3. Principios

- Identidad determinista y reproducible.
- Metadata explícita y trazable.
- Timestamps en UTC (ISO 8601).
- Valores físicos con unidades, escala/offset y nodata explícitos.
- Calidad e incertidumbre diferenciadas.
- Provenance completa.
- Arrays grandes separados de la metadata (referencia a almacenamiento, no
  matrices serializadas en JSON).
- Contrato versionado (V1.x compatible, V2 ruptura).

## 4. Modelo conceptual

El objeto raíz distingue explícitamente la naturaleza del dato mediante
`data_class`:

`OBSERVATION`, `SCIENTIFIC_PRODUCT`, `DERIVED_PRODUCT`, `MODEL`, `REANALYSIS`,
`STATISTICS`, `CLASSIFICATION`, `CARTOGRAPHY`, `BASEMAP`, `FIELD_OBSERVATION`.

No se asume que todo dataset es una "imagen".

## 5. Estructura (objeto raíz)

```
{
  contract      # nombre y versión del contrato
  identity      # id determinista y versión
  data_class    # naturaleza del dato (enum)
  source        # proveedor/misión/plataforma/instrumento/colección
  product       # producto/nivel de procesamiento/versión
  acquisition   # tiempos de adquisición
  temporal      # resolución y cobertura temporal (opcional)
  spatial       # CRS, bounds, resolución, geometría, tile
  processing    # tipo de procesamiento y transformaciones (opcional)
  data          # descriptor del dato (raster|vector|time_series|multidimensional)
  quality       # estado y calidad (dataset/pixel/incertidumbre)
  provenance    # trazabilidad completa
}
```

## 6. Identity

ID determinista: `{source}_{product}_{datetime}_{tile|granule|aoi}_{version}`.

- Componentes normalizados a mayúsculas, sin caracteres especiales.
- `datetime` en UTC, precisión según el producto (segundos para escenas,
  horas para reanálisis, año para datasets estáticos).
- `tile|granule|aoi`: si no aplica, se omite (ej. datasets globales).
- `version`: sufijo `_vN` para reprocesamiento.
- Ejemplos:
  - `SENTINEL2_S2MSI2A_20260904T171002_T13RFL_v1`
  - `LANDSAT_LC09_C2L2_20260904_030045_v1`
  - `ERA5LAND_T2M_2026090400_v1`
  - `INEGI_MGN_2024_v1`

Unicidad: un mismo dato (fuente+producto+tiempo+tile+versión) ⇒ mismo ID.

## 7. Temporal

`acquisition`: `start_time` (obligatorio), `end_time`, `observation_time`.
`temporal` (opcional): `temporal_resolution` (ISO 8601 duración, ej. `P5D`),
`duration_seconds`, `time_coverage_start`, `time_coverage_end`.

Soporta instante, intervalo, series temporales, horarios y composiciones.
**No** se confunde acquisition time con processing time.

## 8. Spatial

`crs` (obligatorio), `native_crs`, `epsg`, `bounds` (obligatorio, [oeste, sur,
este, norte] o [oeste, sur, este, norte, min_z, max_z]), `geometry_type`,
`footprint` (GeoJSON, opcional), `transform` (geotransform afin de 6
coeficientes, opcional), `resolution` (`x`, `y`, `unit`), `width`, `height`,
`tile`.

Regla: **CRS nativo ≠ CRS de análisis**. EPSG:32613 (UTM 13N) es el CRS de
análisis por defecto para Sinaloa, no el universal.

Nota: `footprint` y `transform` son derivables de `bounds` + `resolution` +
`width`/`height`; se incluyen como opcionales para interoperabilidad STAC/GIS.

## 9. Raster (`data.kind = "raster"`)

`bands`: lista de `{name, variable, units, dtype, scale, offset, nodata}`.
`dimensions` (`x`, `y`, `band`), `nodata`, `qa_band`, `cloud_mask`.
El array real permanece en el Data Store; el contrato lleva la metadata.

## 10. Vector (`data.kind = "vector"`)

`geometry_type`, `fields`, `feature_count`, `attribute_schema`.

## 11. Series temporales (`data.kind = "time_series"`)

`variable`, `units`, `location`, `temporal_points`, `quality`.

## 12. Multidimensional (`data.kind = "multidimensional"`)

`variables` (lista de bandas), `dimensions` (`name`, `size`, `units`,
`coordinate_reference`), `coordinates`. Permite representar ERA5-Land y otros
productos con ejes `time`, `x`, `y`, `band`, `depth`, `level`.

## 13. Quality

Vocabulario normalizado: `AVAILABLE`, `PARTIAL`, `INVALID`.

Separación explícita:
- `dataset_quality` (estado global del dataset).
- `pixel_quality` (QA, cloud contamination, invalid pixels).
- `uncertainty` (`value`, `unit`, `type`, `confidence`).

Un producto con píxeles inválidos **no** se marca automáticamente `INVALID`
(puede ser `PARTIAL`). No se convierte un píxel sin retorno en lluvia ausente.

## 14. Provenance

`source_url`, `provider`, `original_product`, `download_time`, `processing_time`,
`processing_software`, `processing_version`, `transformations`, `checksum`,
`license`, `citation`, `parent_dataset`. Permite reconstruir cómo se obtuvo el
dato normalizado.

## 15. Processing

`processing_type`: `NATIVE`, `NORMALIZED`, `DERIVED`, `REPROJECTED`,
`RESAMPLED`, `COMPOSITED`, `AGGREGATED`. `transformations`: lista de
operaciones aplicadas. Nunca se sobrescribe silenciosamente el dato original.

## 16. Uncertainty

`value`, `unit`, `type`, `confidence`. La ausencia de incertidumbre es
representable (`value: null`); no se inventan valores.

## 17. License / Access

`provenance.license`, `attribution` (vía `provenance.citation`), y metadata de
acceso. **No** se almacenan credenciales ni tokens.

## 18. Ejemplos

Ver `contracts/examples/` (Sentinel-2 L2A, Sentinel-1 GRD, Landsat, ERA5-Land,
INEGI/SIAP vector). Ejemplos mínimos, sin datos completos.

## 19. Reglas de compatibilidad

- **Cambio compatible (V1.x):** añadir campos opcionales, añadir valores a
  enums (no quitar), añadir `data.kind`. Un consumidor V1.0 ignora lo desconocido.
- **Cambio incompatible (V2.0):** eliminar/renombrar campos obligatorios,
  cambiar semántica, cambiar el modelo de identidad.

## 20. Limitaciones

- El contrato no acopla a SQLite, COG, Zarr, GeoParquet ni PostGIS (decisiones
  de implementación del Data Store, S-A.2).
- Los arrays científicos grandes no se serializan en JSON.
- La precisión de `dtype` es la del valor físico normalizado (no la del formato
  fuente).
- `nodata` unifica los conceptos de nodata y fill_value (cuando la fuente los
  distinga, se documenta en `provenance`/`processing`).
- El orden de `bounds` es [oeste, sur, este, norte] (convención documental, no
  forzado por regex en el schema).

## 21. Validación del schema

El JSON Schema (Draft 2020-12) usa `format: "date-time"`. La validación de
`format` **no** es automática en `jsonschema`: el consumidor debe instanciar el
validador con `format_checker` (o registrar un checker `date-time`). El
proyecto de tests (`tests/test_contract_schema.py`) registra un checker propio
para `date-time`. Referencia: `Draft202012Validator(schema, format_checker=...)`.
