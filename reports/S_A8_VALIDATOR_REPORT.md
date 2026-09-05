# S-A.8 — Validator — Reporte

## Estado

**READY_FOR_REVIEW** (Validator V1 implementado y validado offline).

## Archivos

- Creados: `app/validators/__init__.py`, `app/validators/base.py`,
  `app/validators/sentinel2.py`, `tests/test_sentinel2_validator.py`,
  `docs/EO_GE_VALIDATOR.md`, `reports/S_A8_VALIDATOR_REPORT.md`.
- Modificados: memoria (`EARTH_OBSERVATION_PROJECT_STATE.json`).

## Reglas implementadas

- Nivel contrato: JSON Schema V1.0 (`jsonschema`).
- Nivel semántico: identity, temporal, spatial (CRS/bbox/resolución), raster,
  quality (cloud cover), provenance.
- Sentinel-2: plataforma/instrumento/nivel/tile MGRS/coherencia CRS-tile/bandas.
- Clasificación AVAILABLE / PARTIAL / INVALID con códigos deterministas.

## Tests

`python -m unittest discover -s tests -p "test*.py"` → **79 passed / 0 failed**
(24 contrato + 16 conector + 18 normalizador + 21 validador).

## Resultado

79/79 en verde.

## Ejemplos de ataques detectados

- Contrato inválido (falta `identity`) → INVALID (SCHEMA_INVALID).
- datetime inválido → INVALID.
- CRS inválido → INVALID (CRS_INVALID).
- resolución negativa → INVALID (RESOLUTION_INVALID).
- cloud cover 150 / -5 → INVALID (CLOUD_COVER_OUT_OF_RANGE).
- bbox con oeste>este → INVALID (BBOX_INVALID).
- checksum ausente → PARTIAL (CHECKSUM_MISSING).
- plataforma landsat-8 en Sentinel-2 → INVALID (S2_PLATFORM_INVALID).
- epsg 32613 con tile T12RYP → error S2_CRS_TILE_MISMATCH.

## Decisiones nuevas

- Validador puro (no modifica entrada); verificada inmutabilidad.
- Errores → INVALID; warnings → PARTIAL; ausencia de opcionales no degrada a INVALID.
- Códigos de error deterministas.

## Limitaciones

- No valida contenido de arrays (solo metadata del contrato).
- `format: date-time` depende del format_checker.

## Confirmaciones

- No se descargaron datasets.
- Radar Engine no fue modificado.
- S-A.9 NO iniciada.
