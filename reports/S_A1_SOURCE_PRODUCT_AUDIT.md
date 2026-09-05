# S-A.1 — SOURCE & PRODUCT AUDIT
## EARTH OBSERVATION & GEOSPATIAL INTELLIGENCE ENGINE (EO-GE ENGINE)

---

## 1. Objetivo

Auditar de forma preliminar las fuentes y productos de observación terrestre
candidatos para el EO-GE ENGINE, diferenciando su naturaleza científica,
cobertura, resoluciones, variables, formatos, APIs, autenticación, licencias y
utilidad para agricultura/meteorología/hidrología, con enfoque en **México y
Sinaloa**.

## 2. Metodología

- Auditoría de escritorio (desk audit) basada en conocimiento público
  establecido de cada fuente/producto.
- **Ninguna fuente se considera `APPROVED` todavía**; los datos precisos de
  APIs, versiones y límites deberán confirmarse contra documentación oficial
  antes de la implementación (S-A.5/S-A.6).
- `AUDIT_STATUS = PARTIAL_AUDIT` indica que la fuente requiere confirmación
  oficial de algunos campos (URL/API/licencia/versión exactas).
- No se descargaron datasets ni se escribió código de producción.

## 3. Fuentes y productos auditados

### NASA (Earthdata)
- **MODIS** (Terra/Aqua) — reflectancia superficial, NDVI, LST, ET. 250 m–1 km, diario, histórico 2000–presente.
- **VIIRS** (SNPP/NOAA-20/21) — sucesor de MODIS. 375–750 m, diario, LST, incendios.
- **SMAP** — humedad del suelo (L-band radar/radiómetro). ~9/36 km, revisita ~2–3 días, desde 2015.
- **GPM IMERG** — precipitación estimada (satélite). 0.1° (~11 km), 30 min, 2000–presente.
- **ECOSTRESS** — LST/evapotranspiración desde ISS. 70 m, no global continuo.
- **NASA FIRMS** — fuego activo (VIIRS 375 m / MODIS 1 km).
- **NASA Earthdata** — portal/API de acceso (requiere Earthdata Login).

### Copernicus (ESA)
- **Sentinel-1** — SAR banda C. GRD 10 m, ~6 días (2 satélites). Backscatter (VV/VH). **No es radar meteorológico**.
- **Sentinel-2** — MSI óptico. 10/20/60 m, 13 bandas, ~5 días. Nivel-1C/2A, máscara de nubes (SCL). Libre (CC-BY).
- **Copernicus DEM** — modelo de elevación global (GLO-30, 30 m) y GLO-90.
- **ESA WorldCover** — cobertura terrestre global 10 m (2020/2021).
- **Copernicus Data Space Ecosystem** — acceso unificado (catálogo STAC, APIs OData/S3).

### USGS
- **Landsat 8/9** (OLI/TIRS) — 30 m, 11 bandas, 16 días. Collection 2 Nivel-1/2. Libre.
- **Landsat Collection 2** — histórico Landsat 4/5/7/8/9 (1982–presente). STAC + EarthExplorer + API (M2M).

### NOAA
- **GOES-16/18** — geoestacionario. ABI 2 km (visible 0.5–1 km), 5–15 min. LST, nubes, vapor de agua.

### México
- **INEGI** — Marco Geoestadístico, MDE, Uso de Suelo y Vegetación, Suelos, cartografía, servicios OGC/APIs.
- **SIAP** — Frontera Agrícola, Estimación de Superficie Agrícola, Firmas Espectrales, Agricultura Protegida, estadísticas.
- **CONAGUA / SMN** — estaciones, precipitación, temperatura, hidrología (SINA, presas, acuíferos).
- **CONABIO** — biodiversidad, ecosistemas, cartografía ambiental, Geoportal.

### Otras
- **SoilGrids (ISRIC)** — propiedades del suelo a 250 m.
- **ERA5-Land (ECMWF/Copernicus)** — **reanálisis** (dato modelado) 0.1° (~9 km), horario, 1950–presente.
- **FAO WaPOR** — ET/biomasa/productividad del agua. **Cobertura: África y MENA** (limitado para México/Sinaloa).
- **OpenStreetMap** — **mapa base** (contexto/visualización), NO dato científico.

## 4. Productos candidatos (estructura por producto)

Cada producto candidato se identifica con: satélite, instrumento, colección,
producto, nivel, variable, formato, método de acceso.

| Satélite | Instrumento | Colección/Producto | Nivel | Variable | Resolución | Formato |
|---|---|---|---|---|---|---|
| Sentinel-2A/B | MSI | S2MSI2A | L2A | Reflectancia superficial (B2–B8A, B11, B12) | 10/20 m | SAFE/COG (CDS), STAC |
| Landsat 8/9 | OLI/TIRS | C2 L2 | L2 | Reflectancia superficial + temperatura superficial | 30 m | GeoTIFF (COG), STAC |
| Terra/Aqua | MODIS | MOD09GA/MOD11/MOD13/MOD16 | L2/L3 | Reflectancia, LST, NDVI, ET | 250 m–1 km | HDF-EOS, STAC |
| SNPP/NOAA-20 | VIIRS | VNP09/VNP21 | L2/L3 | Reflectancia, LST | 375/750 m | HDF, STAC |
| SMAP | L-band | SPL2SMAP | L3 | Soil moisture | 9/36 km | HDF5 |
| GPM | GMI+constelación | IMERG | L3 | Precipitación | 0.1° | HDF5/NetCDF |
| GOES-16/18 | ABI | L2 LST/Cloud | L2 | LST, nubes | 2 km | NetCDF |
| Sentinel-1A/B | SAR C | GRD | L1 | Backscatter σ⁰ (VV/VH) | 10 m | SAFE/COG, STAC |
| ERA5-Land | — | reanálisis | L4 | T2m, precipitación, humedad del suelo, radiación | 0.1° | NetCDF (CDS) |
| ECOSTRESS | — | L2/L3/L4 | L2+ | LST, ET | 70 m | HDF5 |

## 5. Matriz maestra

| Source | Provider | Type | Spatial | Temporal | Coverage | Sinaloa | Format | Auth | License | Agric. value |
|---|---|---|---|---|---|---|---|---|---|---|
| Sentinel-2 | ESA/Copernicus | OBSERVATION (óptico) | 10–60 m | ~5 d | Global | SÍ | SAFE/COG | Abierto | CC-BY libre | ALTO |
| Landsat 8/9 | USGS | OBSERVATION (óptico) | 30 m | 16 d | Global | SÍ | GeoTIFF/COG | Abierto | Libre | ALTO |
| MODIS | NASA | OBSERVATION (óptico) | 250 m–1 km | Diario | Global | SÍ | HDF-EOS | Earthdata Login | Libre | ALTO (series largas) |
| VIIRS | NASA/NOAA | OBSERVATION (óptico) | 375–750 m | Diario | Global | SÍ | HDF | Earthdata Login | Libre | ALTO |
| Sentinel-1 | ESA/Copernicus | OBSERVATION (SAR) | 10 m | ~6 d | Global | SÍ | SAFE/COG | Abierto | CC-BY libre | MEDIO-ALTO |
| SMAP | NASA | OBSERVATION (microndas) | 9–36 km | 2–3 d | Global | SÍ | HDF5 | Earthdata Login | Libre | MEDIO (res. gruesa) |
| GPM IMERG | NASA | ESTIMACIÓN (precipitación) | 0.1° | 30 min | Global (60°N–S) | SÍ | HDF5/NetCDF | Earthdata Login | Libre | MEDIO-ALTO |
| GOES | NOAA | OBSERVATION (geoestacionario) | 2 km | 5–15 min | América | SÍ | NetCDF | Abierto | Libre | MEDIO |
| ERA5-Land | ECMWF | REANALYSIS | 0.1° | Horario | Global | SÍ | NetCDF | CDS registro | Copernicus libre | MEDIO |
| SoilGrids | ISRIC | MODEL (suelo) | 250 m | Estático (v2) | Global | SÍ | GeoTIFF | Abierto | CC-BY | MEDIO |
| Copernicus DEM | ESA | MODEL (terreno) | 30 m | Estático | Global | SÍ | GeoTIFF | Abierto | Libre | ALTO (topografía) |
| ESA WorldCover | ESA | CLASIFICACIÓN | 10 m | 2020/2021 | Global | SÍ | GeoTIFF | Abierto | CC-BY | MEDIO-ALTO |
| FIRMS | NASA | PRODUCTO DERIVADO | 375 m/1 km | Diario | Global | SÍ | WMS/GeoJSON/API | Abierto | Libre | MEDIO (incendios) |
| ECOSTRESS | NASA | OBSERVATION (térmico) | 70 m | Intermitente (ISS) | No continuo | Parcial | HDF5 | Earthdata Login | Libre | MEDIO |
| FAO WaPOR | FAO | PRODUCTO DERIVADO | ~100–250 m | Decadal | África+MENA | **NO** | API/GeoTIFF | Registro | Libre | BAJO (sin Sinaloa) |
| INEGI | INEGI | CARTOGRAFÍA/DATOS | variable | variable | México | SÍ | SHP/GeoJSON/WMS | Abierto | Libre (Gob. MX) | ALTO (referencia) |
| SIAP | SIAP | ESTADÍSTICA/VECTOR | variable | variable | México | SÍ | SHP/CSV/API | Abierto | Libre (Gob. MX) | ALTO (ground truth) |
| CONAGUA/SMN | CONAGUA | ESTACIÓN/OBSERVACIÓN | punto | variable | México | SÍ | CSV/API | Abierto | Libre (Gob. MX) | ALTO (validación) |
| CONABIO | CONABIO | CARTOGRAFÍA AMBIENTAL | variable | variable | México | SÍ | SHP/WMS | Abierto | Libre (Gob. MX) | MEDIO |
| OpenStreetMap | OSM | BASEMAP | variable | variable | Global | SÍ | PBF/GeoJSON | Abierto | ODbL | BAJO (no científico) |

## 6. Comparaciones clave

- **Óptico (Sentinel-2 vs Landsat vs MODIS/VIIRS):** Sentinel-2 (10 m, 5 d) es el
  de mayor resolución espacial/temporal para parcelas; Landsat aporta la serie
  histórica más larga (30 m); MODIS/VIIRS aportan frecuencia diaria y series
  temporales largas a menor resolución.
- **Precipitación (GPM vs CONAGUA/SMN vs ERA5-Land vs Radar):** GPM es estimación
  satelital; estaciones SMN son medición puntual (ground truth); ERA5-Land es
  reanálisis; el Radar Engine es medición por radar. Son complementarias, no
  equivalentes.
- **Temperatura:** GOES/MODIS/VIIRS dan *land surface temperature* (radiométrica);
  las estaciones dan *air temperature*; ERA5-Land da temperatura de reanálisis.
  Son variables distintas.
- **Humedad de suelo:** SMAP (radiométrica, gruesa) vs Sentinel-1 (SAR,
  superficial, indirecta) vs ERA5-Land (modelada).
- **Suelo/topografía:** SoilGrids (250 m global) vs INEGI (México, oficial) vs
  Copernicus DEM (terreno 30 m).
- **SAR satelital (Sentinel-1) ≠ radar meteorológico:** el primero mide
  backscatter superficial (humedad/estructura), el segundo mide precipitación y
  velocidad radial atmosférica. Tecnologías distintas.

## 7. Ranking

### TIER 1 — CORE
Sentinel-2, Landsat 8/9, MODIS, VIIRS, Sentinel-1, ERA5-Land.

### TIER 2 — IMPORTANT
SMAP, GPM IMERG, GOES, SoilGrids, Copernicus DEM, ESA WorldCover, NASA FIRMS, INEGI, SIAP, CONAGUA/SMN.

### TIER 3 — COMPLEMENTARY
ECOSTRESS, CONABIO, OpenStreetMap (basemap).

### TIER 4 — FUTURE
drones, estaciones IoT, sensores de campo, maquinaria agrícola.

### TIER 5 — NOT_RECOMMENDED
Mapas comerciales como fuente científica; FAO WaPOR para Sinaloa (cobertura no
incluye México).

## 8. Candidatos MVP

Criterios: valor agrícola, cobertura Sinaloa, disponibilidad/estabilidad,
documentación, automatización, resolución, histórico, costo, interoperabilidad.

1. **Sentinel-2 L2A** (reflectancia superficial 10 m, ~5 d) — base para vegetación/parcelas.
2. **Landsat 8/9 C2 L2** (30 m, histórico) — series temporales largas.
3. **MODIS** (NDVI/LST diario) — series diarias y climatología.
4. **ERA5-Land** (precipitación, T2m, humedad del suelo) — reanálisis de respaldo.
5. **INEGI / SIAP** — referencia geográfica y agrícola oficial de México.
6. **Sentinel-1** (backscatter) — humedad/inundación (posterior).

## 9. Fuentes descartadas (inicial)

| Fuente | Motivo | Evidencia | Alternativa |
|---|---|---|---|
| FAO WaPOR (para Sinaloa) | Cobertura geográfica limitada a África/MENA | Cobertura oficial de WaPOR | ET vía MODIS/ECOSTRESS o cálculo propio |
| Mapas comerciales como dato científico | No trazables científicamente | — | INEGI/OSM como basemap |

## 10. Limitaciones

- Auditoría de escritorio; los detalles de API/versión/licencia deben
  confirmarse con documentación oficial antes de S-A.5/S-A.6.
- `AUDIT_STATUS = PARTIAL_AUDIT` en todas las fuentes (pendiente confirmación
  oficial de campos específicos).
- No se verificó autenticación/cuotas en vivo (Earthdata Login, CDS).
- SMAP y GPM tienen resolución gruesa (no aptas para parcela fina).
- ECOSTRESS no tiene cobertura global continua.

## 11. Decisiones abiertas (OPEN_DECISIONS)

- Formato de almacenamiento raster (COG vs Zarr vs NetCDF).
- Catálogo interno: STAC propio vs catálogo propio vs base espacial (PostGIS).
- Estrategia de descarga y cache.
- Mosaicos / reproyección (CRS objetivo para Sinaloa, p. ej. UTM 13N).
- Catálogo vectorial y de series temporales.
- Selección definitiva de productos/bandas por caso de uso.

## 12. Recomendaciones

1. Proceder a S-A.2 (arquitectura de datos) con TIER 1 confirmado como foco.
2. Confirmar oficialmente APIs/autenticación de Sentinel-2 (CDS), Landsat
   (USGS M2M), MODIS/VIIRS (Earthdata), ERA5-Land (CDS) antes de S-A.6.
3. Definir CRS objetivo (UTM 13N para Sinaloa) y política de nodata/calidad.
4. Mantener separación estricta observación/producto/modelo/reanálisis.

## 13. Referencias oficiales (por confirmar en S-A.5)

- Sentinel-2 / Copernicus Data Space: https://dataspace.copernicus.eu
- Landsat / USGS: https://www.usgs.gov/landsat-missions
- MODIS/VIIRS/SMAP/GPM / NASA Earthdata: https://www.earthdata.nasa.gov
- GOES / NOAA: https://www.nesdis.noaa.gov
- ERA5-Land / Copernicus CDS: https://cds.climate.copernicus.eu
- SoilGrids / ISRIC: https://www.isric.org
- INEGI: https://www.inegi.org.mx
- SIAP: https://www.gob.mx/siap
- CONAGUA: https://www.gob.mx/conagua
- CONABIO: https://www.gob.mx/conabio
- OpenStreetMap: https://www.openstreetmap.org
