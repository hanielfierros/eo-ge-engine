# S-A.17 — Requisitos de Bandas y Decisión de Adquisición

- Fecha: 2026-09-06
- Motor: EO-GE Engine
- Fase: S-A.17 (NDMI / NDWI / SAVI)

## Bandas requeridas por índice

| Índice | Fórmula | Bandas Sentinel-2 |
|---|---|---|
| SAVI | `((NIR − RED) / (NIR + RED + L)) · (1 + L)`, L=0.5 | NIR = **B08**, RED = **B04** |
| NDMI | `(NIR − SWIR) / (NIR + SWIR)` | NIR = **B08**, SWIR = **B11** |
| NDWI (McFeeters) | `(GREEN − NIR) / (GREEN + NIR)` | GREEN = **B03**, NIR = **B08** |

## Bandas disponibles (materializadas)

- **B04** — reflectancia COG (`SENTINEL2_..._T12RYP_B04_REFL_v1`), S-A.16.
- **B08** — reflectancia COG (`SENTINEL2_..._T12RYP_B08_REFL_v1`), S-A.16.

## Bandas faltantes

- **B03** (GREEN) — requerida por NDWI. NO materializada.
- **B11** (SWIR) — requerida por NDMI. NO materializada.

El `storage/source_cache` y `storage/normalized` solo contienen `B04_10m.jp2` y
`B08_10m.jp2` (S-A.15 / S-A.15.1). No existen `B03` ni `B11` localmente.

## Decisión de adquisición

**Opción A (elegida):** procesar únicamente **SAVI** ahora (B04 + B08 disponibles);
dejar **NDMI y NDWI en estado PENDING** (requieren B03/B11).

Justificación:

1. **Coherencia con S-A.15/S-A.16**: solo B04 y B08 fueron ingeridos y convertidos a
   reflectancia COG. B03/B11 no forman parte de los productos materializados.
2. **Reproducibilidad**: obtener B03/B11 exige descarga desde CDSE con un `CDSE_TOKEN`
   OIDC válido (no persistido; requiere adquisición externa). Sin esa descarga no hay
   inputs reproducibles.
3. **Reglas S-A.17**: no se debe "inventar bandas" ni usar sustituciones incorrectas
   (B04 como SWIR, B08 como GREEN). NDMI/NDWI sin B03/B11 serían productos incompletos.
4. **Infraestructura existente**: el conector `Sentinel2L2AConnector` y la ingesta
   incremental (`ingest_sentinel2_asset`) ya soportan materializar `B03_10m`/`B11_20m`
   de forma controlada, con checksum, cache/source/normalized/derived separados y
   trazabilidad CDSE. Esa etapa queda **fuera de S-A.17** y se ejecutará en una fase
   posterior controlada si se decide obtener B03/B11.

**Decisión NO tomada (fase posterior):** materialización de B03/B11 (y, con ello,
habilitar NDMI y NDWI). Requiere `CDSE_TOKEN` y autorización explícita para descargar.

## Resultado

- SAVI: **procesado** (B04/B08).
- NDMI: **PENDING** (falta B11).
- NDWI: **PENDING** (falta B03).

---

## Adquisición B03/B11 — intento controlado (2026-09-06)

Se ejecutó la microfase de adquisición/materialización de B03 y B11 reutilizando el
conector `Sentinel2L2AConnector` existente (sin crear un downloader nuevo).

### Producto localizado (PASS)

Discovery STAC por `ids` devolvió exactamente el producto:

`S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402`

(`sentinel-2b`, tile `MGRS-12RYP` → `T12RYP`, cloud cover 20.24 %, processing L2).

### Assets B03/B11 (metadata oficial CDSE/STAC, verificada)

| Campo | B03 (GREEN) | B11 (SWIR) |
|---|---|---|
| asset | `B03_10m` | `B11_20m` |
| resolución nativa | **10 m** | **20 m** |
| shape | [10980, 10980] | [5490, 5490] |
| roles | data, reflectance, `sampling:original`, gsd:10m | data, reflectance, `sampling:original`, gsd:20m |
| media type | image/jp2 | image/jp2 |
| href oficial | `https://download.dataspace.copernicus.eu/odata/v1/Products(ee5dd333-d92c-4d66-9043-7e2cc9113965)/.../R10m/.../B03_10m.jp2/$value` | `.../R20m/.../B11_20m.jp2/$value` |
| checksum oficial (multihash `1620` = sha3-256) | `1620` + `96fff5f922755e4cabdd3fb71861b65890980f838b73e611182b98eb7d78cc86` | `1620` + `bfa7206b25be8bd07b9300e2a099e6bac2476383b35128ce8486c237d2000d34` |

Confirma la expectativa científica: B03 = 10 m, B11 = 20 m (B11 **no** se convierte a
10 m en esta etapa).

### Bloqueo de descarga (BLOCKED)

Ambos assets declaran `auth_refs = ['s3', 'oidc']` → la descarga OData exige
autenticación OIDC. El conector verifica la variable de entorno `CDSE_TOKEN`
(alias `CDSE_ACCESS_TOKEN`) y, al estar **ausente**, eleva:

```
AuthenticationError: descarga requiere autenticacion OIDC (variable CDSE_TOKEN ausente)
```

Sin token OIDC válido no es posible materializar B03/B11 de forma reproducible. No se
descargó nada, no se fabricó ninguna banda y no se modificó ningún activo existente.

### Estado de adquisición

- B03: **BLOCKED** (falta `CDSE_TOKEN`).
- B11: **BLOCKED** (falta `CDSE_TOKEN`).

La infraestructura de ingesta incremental (S-A.15.1) está lista para incorporar
`B03_10m` y `B11_20m` cuando se disponga de un `CDSE_TOKEN` OIDC válido exportado en
el entorno. S-A.17 continúa `PARTIAL / READY_FOR_REVIEW` (NDMI/NDWI pendientes).

---

## Adquisición B03/B11 — MATERIALIZADA (2026-09-06)

Con `CDSE_TOKEN` OIDC presente en el entorno, se materializaron B03 y B11 reutilizando
`Sentinel2L2AConnector` + `ingest_sentinel2_asset` incremental (sin resamplear, sin
reproyectar, sin convertir a reflectancia, sin COG, sin calcular NDWI/NDMI).

| Campo | B03 (GREEN) | B11 (SWIR) |
|---|---|---|
| asset | `B03_10m` | `B11_20m` |
| estado | **MATERIALIZED** | **MATERIALIZED** |
| tamaño (bytes) | 43 886 669 | 12 508 068 |
| SHA-256 local | `895d747e1fc75b15b06bc4f27d274d1d4aece0c81717c10330c9c72c4bd94e57` | `7cd433ef5b8b1dde26753e758905e9c83b0be6469b91d7edc1cd3d8a66eb6989` |
| checksum oficial CDSE | `OFFICIAL_SHA3_256_MATCH` (`1620` `96fff5f9…`) | `OFFICIAL_SHA3_256_MATCH` (`1620` `bfa7206b…`) |
| resolución nativa | **10 m** | **20 m** (conservada) |
| CRS | EPSG:32612 | EPSG:32612 |
| dimensiones (rasterio) | 10980×10980 | 5490×5490 |
| catálogo | YES (asset `B03_10m`) | YES (asset `B11_20m`) |

Integridad confirmada: `store.verify()` = True; B04, B08 y SAVI intactos (SHA-256
recalculados e idénticos a los registrados).

Resultado: **NDMI y NDWI quedan habilitados** (inputs materializados) para una fase
posterior. **NO se calcularon en esta fase.** S-A.17 = `PARTIAL / READY_FOR_REVIEW`.
