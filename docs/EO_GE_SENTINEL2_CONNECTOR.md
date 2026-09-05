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

La descarga requiere autenticación:
- Assets de bandas/metadata: `s3://` (credenciales S3 de CDSE).
- Asset `Product`: URL OData `https://download.dataspace.copernicus.eu/odata/...`
  que requiere token OpenID Connect (401 sin token).

El token se lee de la variable de entorno `CDSE_TOKEN`. No se almacenan
credenciales en el código ni en Git.

## 8. Descarga

`download(ref, dest, asset_name)` descarga un asset por su `href` (solo
esquema HTTP(S)). Los assets `s3://` no están soportados en S-A.6
(`UnsupportedAssetError`).

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

- Solo HTTP(S) para descarga; S3 no implementado.
- La descarga real requiere credenciales CDSE (no disponibles en desarrollo).
- No se implementó el Normalizer (pertenece a S-A.7).

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
