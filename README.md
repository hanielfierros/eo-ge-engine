# EARTH OBSERVATION & GEOSPATIAL INTELLIGENCE ENGINE (EO-GE ENGINE)

Infraestructura científica y geoespacial para integrar, normalizar, validar,
almacenar, catalogar y consultar observaciones terrestres.

**No** es un descargador de imágenes, un visor ni un sistema de “IA agrícola”.

Una imagen visual **no** es automáticamente un dato científico: se conserva
fuente, producto, sensor, tiempo, CRS, variable, unidad, calidad, nodata y
procedencia.

## Estado

- Contrato: **EO-GE NORMALIZED DATA CONTRACT V1.0** (`FROZEN`)
- Primer conector de producción: Sentinel-2 L2A (Copernicus Data Space, STAC)
- Cadena: Connector → Source Representation → Normalizer → Validator → Data Store → Catalog → GeoData Interface
- Auditoría técnica S-A.13: **APPROVED_WITH_WARNINGS** (0 CRITICAL; 2 HIGH residuales aceptados)
- Independiente del Radar Meteorological Intelligence

## Requisitos

- Python 3.10+
- `pip install -r requirements.txt`

No se requieren credenciales para ejecutar los tests (suite offline).

El token CDSE, si se usa descarga real, se lee de `CDSE_TOKEN`. No se
almacenan secretos en el repositorio.

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Estructura

```
app/          conectores, normalizers, validators, storage, catalog, geodata
contracts/    JSON Schema V1.0 y ejemplos
config/       settings.example.json (sin credenciales)
docs/         arquitectura y capas
reports/      reportes de fase S-A.1–S-A.13
tests/        unitarias, integración y adversariales (offline)
```

`storage/`, `catalog/` (SQLite local), `source_cache/` y datasets no se versionan.

## Limitaciones conocidas (S-A.13)

- El `deterministic_id` Sentinel-2 no incluye el processing baseline ESA (`Nxxxx`).
- `spatial.bounds` se copia del bbox STAC (WGS84) mientras `spatial.crs` es el CRS nativo.
- Descarga real CDSE condicionada a autenticación; assets `s3://` no implementados.

Detalle: `reports/S_A13_TECHNICAL_AUDIT_REPORT.md`.
