# S-A.15 — Sentinel-2 Real Ingestion Recovery

## 1. Problema

S-A.14 dejó el discovery Sentinel-2 L2A **operativo** y la ingesta **bloqueada**:

- STAC Item real descubierto.
- href primario de bandas = `s3://eodata/...`.
- descarga HTTPS del asset `Product` / OData = **HTTP 401**.
- storage y catalog EO-GE vacíos de bytes Sentinel-2.

STAC Item ≠ bytes de observación. El criterio de esta fase es materializar
**al menos una banda L2A real** (preferente `B04_10m`), verificarla, almacenarla
y catalogarla.

## 2. Causa del bloqueo

Causa verificada (2026-09-05), no especulativa:

1. El catálogo STAC de CDSE es **público**. Discovery no exige token.
2. El href primario de `B04_10m` es `s3://` con `auth:refs: ["s3"]`.
3. CDSE declara un **alternate oficial HTTPS** en el mismo asset:
   `assets.B04_10m.alternate.https.href` →
   `https://download.dataspace.copernicus.eu/odata/v1/Products(<uuid>)/Nodes(...)/$value`
   con `auth:refs: ["oidc"]`.
4. Ese endpoint, **sin** `Authorization: Bearer`, responde **HTTP 401**
   (`Content-Type: application/json`).
5. En este entorno **no existe** `CDSE_TOKEN` / `CDSE_ACCESS_TOKEN`.
6. S-A.6 rechazaba `s3://` y no leía `alternate.https`. Eso convertía un
   asset recuperable por HTTPS OIDC en `UnsupportedAssetError`.

El 401 **no** se debe a un endpoint inventado ni a un item inexistente.
El producto objetivo sigue publicado.

## 3. Mecanismo de acceso (estrategia A/B)

Orden evaluado:

| Estrategia | Ruta | Decisión |
|---|---|---|
| A | HTTPS autenticado OData (`alternate.https.href`) + Bearer OIDC | **Adoptada** |
| B | Misma ruta, expuesta por STAC alternate-assets | **Equivalente a A** |
| C | Cliente S3 (`s3://eodata` + credenciales S3 CDSE) | No implementada (dependencia pesada innecesaria si A funciona) |
| D | `BLOCKED_BY_EXTERNAL_ACCESS` | No aplica: token OIDC válido obtenido |

No se construye `https://` concatenando bucket/key. Solo se usa el href
HTTPS que el propio STAC publica en `alternate`.

## 4. Autenticación

Mecanismo oficial CDSE (OIDC):

- Token endpoint:
  `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
- **No** usar `https://copernicus.eu` (no es OIDC).
- Cliente público documentado: `client_id=cdse-public` (password grant) **o**
  `grant_type=client_credentials` con un OAuth client de la cuenta CDSE.
- EO-GE **no** solicita usuario/contraseña. El operador obtiene el access
  token fuera del motor y exporta:

```text
CDSE_TOKEN=<access_token>
```

Alias aceptado: `CDSE_ACCESS_TOKEN` (mismo Bearer).

Reglas:

- No se escribe el token en JSON, CSV, logs, tests, metadata ni Git.
- Cadena vacía = ausente.
- Si el asset/alternate declara `oidc` y no hay token: error permanente
  (no retry).
- `.gitignore` ya cubre `.env`, `*.token`, `credentials.*`, `secrets.*`.

Para una descarga real controlada (no forma parte de la suite offline):

```text
EO_GE_REAL_INGEST=1
CDSE_TOKEN=<access_token>
python -m unittest tests.test_sentinel2_ingestion.TestRealIngestExternal -v
```

## 5. Asset strategy

Preferencia: `B04_10m` (10 m, rojo; habilita NDVI futuro con B08).

Flujo:

```text
STAC Item
 → resolve_official_https_href (http(s) primario o alternate.https)
 → Bearer si oidc
 → descarga de UN asset (no el SAFE completo)
 → SHA-256 local
 → comparación con checksum oficial si el algoritmo es inequívoco
 → magic JPEG2000
 → LocalDataStore (source_cache + normalized)
 → Catalog + GeoDataInterface
```

No se descargan múltiples escenas. No se calcula NDVI/NDMI/NDWI/SAVI.

## 6. Storage

Exclusivamente `LocalDataStore`:

```text
source_cache/<product_id>/<asset>.jp2
normalized/<deterministic_id>/metadata.json
normalized/<deterministic_id>/files/<asset>.jp2
.staging/  (escritura atómica interna del store)
```

Descarga: `*.part` → verify (tamaño, checksum, no vacío) → `Path.replace`.
Nunca un parcial como archivo final.

## 7. Checksum

- Siempre se calcula **SHA-256** local del archivo (identidad EO-GE).
- CDSE publica `file:checksum` como **multihash hex**. En el producto
  objetivo el prefijo es `1620` = **sha3-256** (32 bytes), no SHA-256
  (`1220`).
- Si el checksum oficial es sha2-256 (`1220` o 64 hex inequívoco):
  `OFFICIAL_SHA256_MATCH`.
- Si es sha3-256 (`1620`): se compara con `hashlib.sha3_256` y se etiqueta
  `OFFICIAL_SHA3_256_MATCH`. El campo `checksum` del recurso sigue siendo
  SHA-256 local.
- Si el algoritmo no es inequívoco: `SHA-256_LOCAL`. **No** se compara
  SHA-256 contra sha3-256.

## 8. Retry

Reintentos con backoff: 429, 5xx, timeout, conexión, archivo vacío,
`Content-Length` inconsistente.

No retry: 401, 403, 404, `s3://` sin alternate HTTPS, OIDC ausente.

## 9. Recovery

- `.part` se elimina al iniciar y tras fallo.
- Cache JP2 corrupto (magic inválida) se borra y se redescarga.
- Producto normalizado corrupto (`verify()` falso) se elimina y se vuelve
  a `put_metadata` + `put_file` desde bytes verificados.
- Destino existente e íntegro: se reutiliza (idempotente).

## 10. Catalog

No se registra un item sin archivo físico.

Tras `put_file`, el adapter recibe `materialized_files` con href relativo
seguro (`normalized/<id>/files/B04_10m.jp2`), tamaño y checksum.

Contrato: **CATALOG ENTRY ↔ PHYSICAL FILE**.

## 11. GeoDataInterface

Sin API nueva. Tras ingesta:

- `search(collection="sentinel-2-l2a")`
- `get_item` / `get_metadata` / `get_asset("B04_10m")`
- `get_file(id, "B04_10m.jp2")`
- `exists` / `verify`

## 12. Seguridad

- Token nunca en excepciones, SourceRepresentation, metadata.json ni logs.
- Tests comprueban ausencia del placeholder de token en excepciones y
  metadata.
- `test_adversarial.TestNoSecretLeak` sigue en verde.

## 13. Resultado S-A.15

Estado: **COMPLETED / PASS**. Fase **CLOSED**. S-A.16 **NOT_STARTED**.

Producto `S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402`,
Item `SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1`.

B04+B08 materializados e íntegros. Catalog consistente. 189 passed / 1 skipped.

Banda `B04_10m` (44 822 636 bytes, SHA-256 local
`bf94442d24e568e478290970a6037ea77c6af47e673cffb748cca36b17b18687`,
`OFFICIAL_SHA3_256_MATCH`, CRS EPSG:32612, scaling no aplicado).

## 13.1 Intento B08 — BLOCKED (histórico)

2026-09-05: primer intento con token de audiencia insuficiente. Discovery STAC
del producto objetivo OK; `B08_10m` tiene `alternate.https` OIDC. La descarga
OData devolvió **HTTP 401** `DAT-ZIP-609` `Token audience not allowed`. No se
usó otra autenticación. B04 permanece intacto. B08 no se materializó en ese
intento. S-A.16 no iniciada.

## 13.2 B08 real — COMPLETED

2026-09-05: token OIDC regenerado aceptado por
`download.dataspace.copernicus.eu` (sonda HTTP 200). Ingesta incremental
S-A.15.1 de **solo** `B08_10m.jp2` sobre el mismo Item
`SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1`.

| Campo | Valor |
|---|---|
| path | `storage/normalized/SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1/files/B08_10m.jp2` |
| size | 47052534 |
| SHA-256 local | `82395f6a56307a505d0e508b64a5ae679046cc879897ac1250ba574f7b29a970` |
| CDSE `file:checksum` | multihash `1620` / sha3-256 `6b4a09ad6f7a3181dd0f766e815fab9be094321dcf920ab42c366f65fad32015` |
| CHECKSUM_VERIFICATION | `OFFICIAL_SHA3_256_MATCH` |
| JP2 magic | OK |
| Catalog | asset `B08_10m` añadido; `B04_10m` conservado |
| B04 | intacto (44822636 / `bf94442d24e568e478290970a6037ea77c6af47e673cffb748cca36b17b18687`) |

No se recalculó B04. No se inició S-A.16.

## 14. Limitaciones

- Cliente S3 no implementado; la vía usada es HTTPS OData (`alternate.https`).
- Validación raster de esta fase: firma JP2 + metadata STAC + checksum
  oficial. No se añade rasterio/GDAL; no se abren arrays ni se aplica scaling.
- `grid:code` CDSE llega como `MGRS-12RYP`; EO-GE lo normaliza a `T12RYP`.
  CRS nativo del asset B04 = EPSG:32612. No se fuerza EPSG:32613.
- Indices espectrales y BRAIN_00 quedan fuera de S-A.15.
- El access token OIDC caduca (~1800 s). No persistirlo. El endpoint
  `https://copernicus.eu` no es OIDC.

## Referencias oficiales

- STAC CDSE: `https://stac.dataspace.copernicus.eu/v1/`
- Colección: `sentinel-2-l2a`
- OData download: `https://download.dataspace.copernicus.eu/odata/v1/Products(...)/$value`
- Documentación CDSE Authentication / OData product download
- STAC Authentication extension (`auth:refs` oidc/s3)
- STAC Alternate Assets (`alternate.https.href`)
