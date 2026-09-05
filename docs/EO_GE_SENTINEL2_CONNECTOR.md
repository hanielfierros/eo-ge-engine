# Sentinel-2 L2A Connector (CDSE)

Primer conector de producción del EO-GE Engine. Conecta con el catálogo STAC
del **Copernicus Data Space Ecosystem (CDSE)** para el producto
**Sentinel-2 Level-2A**.

## 1. Propósito

Demostrar la cadena real: `CDSE → STAC Discovery → Item S2 L2A → selección →
metadata → descarga controlada → SHA-256 → SourceRepresentation`.

## 2. CDSE

- Proveedor: ESA / Copernicus.
- STAC endpoint: `https://stac.dataspace.copernicus.eu/v1/`
- Colección: `sentinel-2-l2a`
- Versión STAC: 1.1.0

## 3. Endpoint

`POST /v1/search` con cuerpo JSON: `{collections: [...], bbox: [...],
datetime: "...", limit: N}`. (El `bbox` es una lista de 4 números, no una
cadena separada por comas.)

## 4. Colección

`sentinel-2-l2a` (Sentinel-2 Level-2A, reflectancia superficial, tiles MGRS).

## 5. Discovery

Consulta por AOI (bbox), intervalo temporal, y límite de resultados. El
`cloud_cover_max` se aplica en la selección (no en el STAC query).

## 6. Filtros

- Espacial: `bbox` [oeste, sur, este, norte].
- Temporal: `datetime` (`inicio/fin`).
- Límite de resultados.

## 7. Autenticación

El catálogo STAC (`POST /v1/search`) es público. La **descarga** de bytes
requiere OIDC:

- El href primario de las bandas es `s3://eodata/...` (`auth:refs: s3`).
- CDSE publica `alternate.https.href` (OData Node `$value`) con `auth:refs: oidc`.
- Sin Bearer token, ese HTTPS responde **HTTP 401**.
- El token se lee de `CDSE_TOKEN` (alias `CDSE_ACCESS_TOKEN`). Vacío = ausente.
- No se almacenan credenciales en código, metadata, logs ni Git.

## 8. Descarga

`download(ref, dest, asset_name)` (S-A.15):

1. Si el href primario es HTTP(S), se usa.
2. Si es `s3://`, se usa **solo** un `alternate.*.href` HTTP(S) declarado por STAC.
3. No se inventa `s3://bucket/key → https://...`.
4. Sin alternate HTTPS oficial: `UnsupportedAssetError`.
5. Si el asset/alternate declara `oidc` y no hay token: `AuthenticationError` (fail-fast).
6. Escritura atómica: `*.part` → verify → rename. Retry en 429/5xx/timeout/integridad transitoria. 401/403/404 no reintentan.

## 9. Retry

Retry con backoff exponencial para errores transitorios (429, 5xx, timeout),
límite de intentos. 401/403/404 son permanentes (no retry).

## 10. Integrity

SHA-256 local del archivo descargado (`verify`), y `checksum:multihash` del
asset si el proveedor lo proporciona.

## 11. Source Representation

`build_source_representation()` produce el objeto intermedio (source, product,
source_id, source_metadata, acquisition, spatial, temporal, resource, checksum,
provenance), conservando el STAC Item original.

## 12. Configuración

`config/settings.example.json` define el endpoint y la colección. El token se
toma de `CDSE_TOKEN`.

## 13. Tests

`tests/test_sentinel2_connector.py` — 16 tests offline (fixtures + mocks de
HTTP). No dependen de CDSE.

## 14. Limitaciones

- Cliente S3 no implementado; la vía oficial usada es HTTPS OData (`alternate.https`).
- La descarga real requiere `CDSE_TOKEN` (OIDC). Sin token el estado es BLOCKED.
- No se calcula NDVI ni se aplica `raster:scale`/`offset` en el conector.

## 15. Ejemplo de ejecución

```python
from app.connectors.sentinel2 import Sentinel2L2AConnector
from app.connectors.base import DiscoveryQuery

conn = Sentinel2L2AConnector()
refs = conn.discover(DiscoveryQuery(
    collection="sentinel-2-l2a",
    bbox=(-108.6, 25.4, -108.3, 25.7),
    datetime="2026-08-01T00:00:00Z/2026-09-04T00:00:00Z",
    limit=5,
))
item = conn.select_item(refs)
meta = conn.get_metadata(item)
```
