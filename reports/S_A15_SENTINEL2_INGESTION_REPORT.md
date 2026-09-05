# S-A.15 — Sentinel-2 Ingestion Report

Fecha: 2026-09-05  
Motor: EO-GE Engine  
Fase: S-A.15 SENTINEL-2 REAL INGESTION RECOVERY

## Resultado

```text
STATUS = COMPLETED / PASS
CLOSED = YES
S-A.16 = NOT_STARTED
```

S-A.15 **CLOSED**. B04+B08 materializados e íntegros sobre el mismo Item
`SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1`. Catalog consistente.
189 tests PASS.

Se materializaron bandas Sentinel-2 L2A reales (`B04_10m`, `B08_10m`), con
integridad oficial (sha3-256 CDSE), SHA-256 local, almacenamiento atómico,
catálogo y recuperación vía GeoDataInterface. Reingesta del mismo asset:
**idempotente**.

No se calcularon índices. No se aplicó scaling. CRS nativo conservado
(EPSG:32612). Credenciales OIDC **no** se persistieron.

## Producto

| Campo | Valor |
|---|---|
| product_id | `S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402` |
| catalog_id / item_id | `SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1` |
| platform | sentinel-2b |
| processing_level | L2 |
| tile | T12RYP (CDSE `grid:code` = MGRS-12RYP) |
| acquisition | 2026-08-28T17:48:59.024000Z |
| cloud_cover | 20.24 % |
| GSD | 10 m |
| validation_status | AVAILABLE |

## Asset

| Campo | Valor |
|---|---|
| asset_id | B04_10m |
| source | COPERNICUS_DATA_SPACE |
| href primario | `s3://eodata/...` (no usado para descarga) |
| access | `alternate.https.href` OData `download.dataspace.copernicus.eu` |
| type | image/jp2 |
| CRS nativo | EPSG:32612 |
| proj:shape (STAC) | [10980, 10980] |
| dtype | uint16 |
| nodata | 0 |
| raster:scale | 0.0001 (declarado; **no aplicado**) |
| raster:offset | -0.1 (declarado; **no aplicado**) |

## Bytes / checksum / storage / catalog

| Campo | Valor |
|---|---|
| REAL_BYTES | YES |
| FILE_SIZE | 44822636 |
| SHA-256 local | `bf94442d24e568e478290970a6037ea77c6af47e673cffb748cca36b17b18687` |
| CHECKSUM_VERIFICATION | `OFFICIAL_SHA3_256_MATCH` (CDSE `file:checksum` multihash `1620`) |
| JP2 magic | OK |
| source_cache | `storage/source_cache/S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402/B04_10m.jp2` |
| normalized | `storage/normalized/SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1/files/B04_10m.jp2` |
| catalog | item + asset `B04_10m` href relativo `normalized/.../files/B04_10m.jp2` |
| GeoDataInterface | exists / get_asset / get_file / verify = True |
| idempotency | segunda ingesta REUSED, mismo SHA-256 |

## Autenticación

- Endpoint OIDC oficial: `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
- `https://copernicus.eu` **no** es el token endpoint (401/no-OIDC).
- Token Bearer en `CDSE_TOKEN` (no persistido).
- Password grant (`cdse-public`) y `client_credentials` (OAuth client Sentinel Hub) ambos obtuvieron access token HTTP 200 en el endpoint oficial.
- Secretos **no** se escribieron en JSON, tests, metadata ni Git.

## HTTP 401

Sin token: OData HTTPS = 401. Con Bearer válido: descarga 200 y bytes JP2 reales.

## Tests

Gate de cierre (suite con `CDSE_TOKEN` ausente solo en el proceso de prueba):

```text
189 passed
0 failed
0 errors
1 skipped
```

`TestRealIngestExternal` skipped (`EO_GE_REAL_INGEST!=1`). No se interpretó token presente como ausencia.

## Warnings

- rasterio/GDAL no añadido; dimensiones/CRS de pixel no se reabrieron como array (magic JP2 + metadata STAC + checksum oficial).
- Cliente S3 no implementado (no necesario: alternate HTTPS funcionó).
- Timeout de conector por defecto 60 s; la ingesta real usó 600 s.

## Blockers

Ninguno. B04+B08 materializados. S-A.15 CLOSED.

## Integridad de otros proyectos

BRAIN_00, BRAIN_01, Radar Engine: no modificados.

## Git

Commit local: `Complete S-A.15 Sentinel-2 real ingestion`  
NO PUSH

## Next phase

S-A.16 NOT_STARTED. S-B.0 NOT_STARTED.

## Intento B08 (2026-09-05T19:17:01Z) — BLOCKED (histórico)

Objetivo: materializar `B08_10m.jp2` de forma incremental sobre el mismo Item
`SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1` sin tocar B04.

```text
STATUS = BLOCKED
FAILURE_POINT = CDSE OData HTTPS GET alternate.https.href (B08_10m)
HTTP = 401
CODE = DAT-ZIP-609
MESSAGE = Token audience not allowed
```

Hechos verificados en ese intento: token presente pero audiencia rechazada;
B04 intacto; B08 no escrito. Sin autenticación alternativa.

## B08 real (2026-09-05T19:36:19Z) — COMPLETED

Ingesta incremental S-A.15.1. Solo `B08_10m.jp2`. Mismo Item. `alternate.https`
OData + Bearer `CDSE_TOKEN`. Staging atómico. B04 no redescargado.

```text
STATUS = COMPLETED
HTTP = 200
CHECKSUM_VERIFICATION = OFFICIAL_SHA3_256_MATCH
```

| Campo | Valor |
|---|---|
| path | `storage/normalized/SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1/files/B08_10m.jp2` |
| size | 47052534 |
| SHA-256 local | `82395f6a56307a505d0e508b64a5ae679046cc879897ac1250ba574f7b29a970` |
| CDSE sha3-256 | `6b4a09ad6f7a3181dd0f766e815fab9be094321dcf920ab42c366f65fad32015` (multihash `1620`) |
| integridad | JP2 magic OK; `store.verify()` True |
| Catalog | `B04_10m` + `B08_10m` |
| metadata bands | B04 (red) + B08 (nir) |

B04 conservado exactamente:

- path: `storage/normalized/SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1/files/B04_10m.jp2`
- size: 44822636
- SHA-256: `bf94442d24e568e478290970a6037ea77c6af47e673cffb748cca36b17b18687`

Tests offline: 189 collected / 189 passed / 0 skipped / 0 failed / 0 errors.
`TestRealIngestExternal` excluida (no reingiere B04; no interpreta token
presente como ausencia).

S-A.16 NOT_STARTED. BRAIN_00 / BRAIN_01 / Radar Engine no modificados.
Commit local S-A.15. NO PUSH.
