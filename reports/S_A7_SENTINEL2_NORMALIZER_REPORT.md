# S-A.7 — Sentinel-2 L2A Normalizer — Reporte

## Estado

**READY_FOR_REVIEW** (normalizador implementado y validado offline).

## Archivos creados/modificados

- Creados: `app/normalizers/__init__.py`, `app/normalizers/base.py`,
  `app/normalizers/sentinel2.py`, `tests/test_sentinel2_normalizer.py`,
  `tests/fixtures/sentinel2_source_representation.json`,
  `docs/EO_GE_SENTINEL2_NORMALIZER.md`, `reports/S_A7_SENTINEL2_NORMALIZER_REPORT.md`.
- Modificados: `app/connectors/base.py` (campo `collection_metadata` en
  SourceRepresentation), `app/connectors/sentinel2.py` (`get_collection()` +
  `build_source_representation` enriquecido), memoria.

## Mapping implementado

identity determinista, data_class, source, product, acquisition, spatial (CRS
derivado del tile MGRS), data.raster (bandas espectrales con dtype/scale/offset/
nodata), quality (cloud cover), provenance completa.

## Tests

`python -m unittest discover -s tests -p "test*.py"` → **58 passed / 0 failed**
(24 contrato + 16 conector + 18 normalizador).

## Resultado de test suite

58/58 en verde.

## Limitaciones

- No descarga datos ni crea COG/NetCDF/Zarr (Data Store, S-A.9).
- `storage.format="COG"` es declaración de formato canónico; materialización en S-A.9.
- No calcula NDVI ni índices.
- `dtype` se obtiene de `item_assets.data_type`; si falta, falla explícitamente.

## Decisiones nuevas

- Identidad determinista `SENTINEL2_{product}_{datetime}_{tile}_v1`.
- CRS derivado del tile MGRS cuando `proj:epsg` está ausente (verificado en CDSE).
- El conector ahora entrega `collection_metadata` (item_assets) para que el
  normalizador mapee dtype/scale/offset/nodata.
- Falla explícita (NormalizationError) ante ausencia de datos críticos, en vez
  de producir un contrato inválido.

## Confirmaciones

- No se descargaron datasets.
- Radar Engine no fue modificado.
- S-A.8 no fue iniciada.
