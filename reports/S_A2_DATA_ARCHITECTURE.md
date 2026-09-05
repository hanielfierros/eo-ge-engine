# S-A.2 — DATA ARCHITECTURE
## EARTH OBSERVATION & GEOSPATIAL INTELLIGENCE ENGINE (EO-GE ENGINE)

---

## 1. Objetivo

Definir la arquitectura técnica de datos del EO-GE Engine, adaptando el patrón
validado del Radar Engine V2-A.4 al carácter geoespacial del proyecto, y
resolviendo las 5 decisiones abiertas de S-A.1. Arquitectura concreta,
implementable, sin complejidad que no aporte valor al MVP.

## 2. Arquitectura

```
SOURCE (STAC/OGC/API/HTTP/S3)
   ↓
CONNECTOR
   ↓
SOURCE REPRESENTATION (raw / fuente)
   ↓
NORMALIZER
   ↓
VALIDATOR (científico + estructural)
   ↓
STANDARDIZED OBSERVATION (raster | vector | time-series)
   ↓
DATA STORE (COG / NetCDF / Parquet)
   ↓
CATALOG (STAC-metadata + SQLite)
   ↓
GEOSPATIAL DATA INTERFACE
   ↓
FUTURE INTERPRETATION ENGINE
```

Reglas de separación (heredadas de S-A.0):
`OBSERVATION`, `SCIENTIFIC_PRODUCT`, `DERIVED_PRODUCT`, `MODEL`, `REANALYSIS`,
`STATISTICS`, `CLASSIFICATION`, `CARTOGRAPHY`, `BASEMAP`, `FIELD_OBSERVATION`
— cada uno con su propia trazabilidad.

## 3. Decisiones (resolución de S-A.1)

| # | Decisión abierta | Resolución |
|---|---|---|
| OD-01 | Formato raster | **COG** para raster 2D/3D (x,y,banda); **NetCDF** para mallas multidimensionales con tiempo; **Zarr** como evolución cloud (no en MVP) |
| OD-02 | Catálogo | **STAC como modelo de metadatos + SQLite como implementación**; evolución a PostGIS/STAC-API sin romper contrato |
| OD-03 | Descarga/cache | **SOURCE CACHE (raw, volátil) / NORMALIZED (canónico) / DERIVED (recalculable)**, staging + escritura atómica + SHA-256 + dedup por ID |
| OD-04 | CRS | Conservar CRS nativo en metadata; **CRS de análisis = EPSG:32613 (UTM 13N)** para Sinaloa; reproyección bajo demanda; no universal |
| OD-05 | Vector / series temporales | **GeoParquet** (canónico vector) + **GeoPackage** (intercambio); **Parquet** (series temporales/tabular) |

## 4. Formatos

| Formato | Rol |
|---|---|
| **COG (Cloud Optimized GeoTIFF)** | Canónico raster 2D/3D: Sentinel-2, Landsat, Sentinel-1, DEM, land cover, soil |
| **NetCDF** | Ingestión + canónico para mallas multidimensionales con tiempo: ERA5-Land, MODIS/VIIRS/SMAP/GPM (pilas) |
| **Zarr** | Evolución para time-series grid grandes / cloud (S-C) |
| **GeoParquet** | Canónico vectorial (parcelas, municipios, cuencas, frontera agrícola) |
| **GeoPackage** | Intercambio vectorial con herramientas GIS |
| **Parquet** | Series temporales tabulares y estadísticas (SIAP, estaciones) |
| GeoJSON | Intercambio ligero |

Convenciones de valor: `float32` para raster (con `nodata`), `scale_factor`/`add_offset`
conservados como metadata (no re-escalar salvo normalización explícita), unidades
y CRS SIEMPRE embebidos, `bounds` y `timestamps` en metadata, calidad/incertidumbre
como bandas o metadata asociada.

## 5. Catálogo

STAC como modelo de metadatos (Collection + Item: `id`, `geometry`, `bbox`,
`datetime`, `properties`, `assets`), implementado en SQLite:

- Tabla `collections` (source, product, license, version, processing_level).
- Tabla `items` (id determinista, datetime, bbox, footprint, CRS, resolution, variables/bandas, checksum, storage_path, quality, provenance, ingest_status).
- Tabla `assets` (variable/banda → archivo, formato, dtype, nodata, checksum).

Responde: qué existe, fuente, producto, fecha/hora, cobertura, resolución, CRS,
variables, calidad, ruta, checksum, versión, licencia, provenance, estado.

Evolución: los metadatos STAC se exponen luego vía STAC-API; SQLite → PostGIS/PostgreSQL
sin cambiar el modelo de metadatos.

## 6. Storage layout (dentro de PROJECT_ROOT)

```
data/                     (gitignored)
├── raw/                  # SOURCE CACHE (descargas crudas, volátil)
├── normalized/           # canónico (COG / NetCDF / GeoParquet / Parquet)
├── derived/              # productos recalculables (índices, agregados)
├── catalog/
│   └── catalog.sqlite    # catálogo + estado
├── staging/              # escritura atómica en curso
└── cache/                # cache temporal de acceso/subset
reports/ tests/ docs/ config/ scripts/ src/
```

Escritura atómica: staging → validar → checksum → rename → catálogo `AVAILABLE`
(patrón del Radar Engine). Interrupción ⇒ el item no aparece disponible; `cleanup_staging()`.

## 7. Cache / retention

| Clase | Política |
|---|---|
| SOURCE CACHE (`raw/`) | Volátil; eliminar tras normalizar (retención corta configurable) |
| NORMALIZED (`normalized/`) | Conservar (fuente primaria normalizada) |
| DERIVED (`derived/`) | Recalculable; conservar o regenerar según costo |
| CACHE (`cache/`) | Volátil, purgable |

Descarga con retry + reanudación (HTTP Range donde aplique); dedup por ID determinista;
SHA-256 por archivo en manifest.

## 8. CRS

- **CRS nativo**: se conserva siempre en metadata (`crs`).
- **CRS de análisis por defecto**: `EPSG:32613` (UTM 13N) para Sinaloa.
- Reprojección bajo demanda (rasterio/rioxarray); datasets globales se mantienen en
  CRS nativo (p. ej. `EPSG:4326`) y se reproyectan al leer.
- Cálculo de áreas/distancias SIEMPRE en CRS proyectado (UTM).
- Compatible con datos vectoriales mexicanos (INEGI usa ITRF2008/UTM; se registra el CRS de origen).

## 9. Raster

Cada raster normalizado (COG) conserva: banda/variable, resolución, tile/granule,
tiempo, footprint/bbox, nodata, QA/cloud-mask (banda o asset), uncertainty (si existe),
CRS, escala/offset, unidades.

- Sentinel-2/Landsat/Sentinel-1 → un COG por tile por fecha (bandas como capas o assets).
- MODIS/VIIRS/SMAP/GPM → NetCDF por variable (pila temporal) o COG por paso temporal.
- Acceso parcial por subconjunto espacial/temporal sin cargar la imagen completa
  (COG permite lectura por ventanas; NetCDF permite slice por tiempo).

## 10. Vector

Canónico **GeoParquet** (columnar, compacto, streaming). Intercambio GeoPackage/GeoJSON.
Soporta: límites administrativos, parcelas, municipios, localidades, cuencas,
acuíferos, carreteras, hidrografía, uso de suelo, frontera agrícola, puntos de estaciones.
Cada dataset vectorial = un asset + metadata (fuente, fecha, CRS, licencia, geometría).

## 11. Series temporales

Representación en **Parquet** largo (una fila por observación): `{entity_id, location,
variable, time, value, unit, quality, source}` para NDVI, LST, precipitación, soil
moisture, ET, variables ERA5-Land, estaciones y observaciones de campo.

Consulta: `variable + ubicación + intervalo temporal + fuente + calidad` sin cargar
imágenes. Extracción de series por píxel/parcela se materializa en Parquet vía el
interprete (fase futura); en S-A se define el esquema.

## 12. Data identity

ID determinista: `{source}_{product/collection}_{datetime}_{tile|granule|aoi}`.

- Ejemplos: `SENTINEL2_S2MSI2A_20260904_T13RFL`, `LANDSAT_LC09_C2L2_20260904_030045`,
  `ERA5LAND_T2M_2026090400`, `INEGI_MGN_2024`.
- `version` para reprocesamiento (p. ej. `_v1`).
- Nunca usar UUID como identidad primaria. Un mismo dato ⇒ mismo ID.

## 13. Quality / provenance

Campos normalizados: `quality`, `QA`, `uncertainty`, `processing_level`, `source`,
`product`, `acquisition_time`, `processing_time`, `provider`, `license`, `source_url`,
`checksum`, `software_version`, `transformation_history`. La metadata científica de
origen se conserva (no se pierde al normalizar).

## 14. Escalabilidad

Diseñado para desarrollo local + Sinaloa + datasets pequeños/series temporales, con
camino claro hacia: multi-región, grandes volúmenes, object storage, STAC-API,
PostGIS y Zarr distribuido. No se implementa infraestructura cloud ahora.

## 15. MVP architecture

Componentes comunes para Sentinel-2 L2A, Landsat 8/9 C2 L2, Sentinel-1 GRD, MODIS,
ERA5-Land, INEGI/SIAP:

- **Connector base** (descarga + autenticación + retry + cache).
- **Normalizer** → `StandardizedObservation` (raster COG / NetCDF / GeoParquet / Parquet).
- **Validator** (estructural: bbox/CRS/nodata/dtype; científico: rangos físicos).
- **Data Store** (escritura atómica + checksum + layout).
- **Catalog** (STAC-metadata + SQLite).
- **GeoData Interface** (get_collection, get_item, get_asset, get_bbox, get_series).

Estos 6 componentes son comunes; cada fuente aporta su connector/normalizer específico.

## 16. Decisiones descartadas

- **PostGIS en S-A.2**: complejidad innecesaria; se adopta SQLite + STAC-metadata y se
  migra a PostGIS solo cuando haya multi-lector/API.
- **Zarr en MVP**: se difiere; NetCDF cubre mallas multidimensionales iniciales.
- **Un único formato para todo**: incorrecto; se separa raster/vector/series.

## 17. Riesgos

- Crecimiento de disco en `normalized/` (COG/NetCDF) — requiere retención explícita.
- Fuga de CRS (olvidar CRS/calidad) — mitigado con validación obligatoria.
- Complejidad del catálogo STAC si se sobredimensiona — se mantiene SQLite simple.
- Reprojección repetida costosa — mitigar con cache de análisis.

## 18. Siguiente fase

**S-A.3 — Normalized Data Contract** (diseño del contrato `EARTH_OBSERVATION_NORMALIZED_DATA_CONTRACT_V1.0`),
con la arquitectura aquí definida como base. No auto-avanzar.
