# S-A.6 — FIRST PRODUCTION CONNECTOR (Sentinel-2 L2A) — Reporte

## 1. Alcance

Implementar y validar el primer conector de producción real del EO-GE Engine
contra el catálogo STAC de CDSE (Sentinel-2 Level-2A).

## 2. Documentación CDSE verificada (esta sesión)

- STAC endpoint: `https://stac.dataspace.copernicus.eu/v1/` (STAC 1.1.0).
- Colección: `sentinel-2-l2a`.
- Search: `POST /v1/search` con cuerpo JSON `{collections, bbox, datetime, limit}`.
- Autenticación: esquemas `s3` (custom-s3) y `oidc` (OpenID Connect).
- Assets: bandas por resolución (`B04_10m`, ... tipo `image/jp2`, href `s3://`),
  `Product` (`.SAFE`, OData HTTPS), metadata (`safe_manifest`, `product_metadata`,
  ...), `SCL_20m` (clasificación de escena).
- Descarga del `Product` (OData) devuelve **HTTP 401 sin token** (confirmado).

## 3. Implementación

- `app/connectors/base.py` — `BaseConnector`, jerarquía de errores,
  `SourceRepresentation`, `DownloadedResource`, capabilities, `sha256_file`.
- `app/connectors/sentinel2.py` — `Sentinel2L2AConnector` (discover, get_metadata,
  select_item, download con retry, verify, build_source_representation).
- `config/settings.example.json` — endpoint y colección; token vía `CDSE_TOKEN`.
- `tests/test_sentinel2_connector.py` — 16 tests offline.

## 4. Item real utilizado

`S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402`
(seleccionado por menor cloud cover: 20.24 %, tile T12RYP).

## 5. Recurso descargado

**Ninguno** (descarga real bloqueada por requisito de acceso). Ver §10.

## 6. Tamaño / checksum

N/A (no se descargó recurso real).

## 7. Tiempos

Discovery real (5 items): ~2.1 s.

## 8. Tests

`python -m unittest discover -s tests -p "test*.py"` → **40 passed, 0 failed**
(24 del contrato + 16 del conector).

## 9. Prueba real

| Paso | Resultado |
|---|---|
| Discovery (STAC search, AOI Guasave) | ✓ 5 items |
| Metadata (Item) | ✓ (gsd=10, platform=sentinel-2b, level=L2) |
| Selection (menor cloud cover) | ✓ |
| Download (real) | ✗ bloqueado por acceso |
| Integrity | — (sin descarga) |
| Source Representation | ✓ (con fixture) |

## 10. Errores encontrados

- Descarga real sin token: assets de bandas/metadata usan `s3://`
  (`UnsupportedAssetError`); el asset `Product` (OData HTTPS) devuelve **401**
  (`AuthenticationError`) sin credenciales CDSE.
- Bug corregido durante S-A.6: el retry de descarga re-lanzaba `last_exc` tras
  un reintento exitoso (se eliminó la comprobación residual).

## 11. Limitaciones

- Solo descarga HTTP(S); S3 no implementado (requiere cliente S3 en una fase
  futura).
- La prueba de descarga real queda condicionada a credenciales CDSE.
- El Normalizer (S-A.7) no se implementó.

## 12. Resultado

**PARTIAL — REAL DOWNLOAD BLOCKED BY ACCESS REQUIREMENT**

Discovery, metadata, selección y Source Representation funcionan con datos
reales; la descarga real requiere autenticación CDSE (no disponible). Los tests
offline (16) y la suite completa (40) pasan. No se simuló éxito en la descarga.
