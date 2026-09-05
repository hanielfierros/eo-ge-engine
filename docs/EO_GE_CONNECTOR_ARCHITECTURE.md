# EO-GE CONNECTOR ARCHITECTURE

**EARTH OBSERVATION & GEOSPATIAL INTELLIGENCE ENGINE (EO-GE ENGINE)** — S-A.5

---

## 1. Objetivo

Definir la arquitectura común de conectores para incorporar fuentes
satelitales, geoespaciales, meteorológicas, hidrológicas, agrícolas y terrestres
sin duplicar lógica, entregando datos compatibles con el contrato congelado
**EO-GE NORMALIZED DATA CONTRACT V1.0**.

## 2. Responsabilidades

El Connector **solo** hace: `descubrir → solicitar → descargar/obtener → verificar → entregar`.

El Connector **NO** hace: normalizar científicamente, validar el contrato final,
transformar valores físicos (salvo lo indispensable para interpretar la respuesta
del proveedor), almacenar permanentemente, ni generar productos derivados.

## 3. Arquitectura

```
SOURCE
   ↓
CONNECTOR  (descubrir / descargar / verificar)
   ↓
SOURCE REPRESENTATION  (fuente original + metadata)
   ↓
NORMALIZER  (→ contrato V1.0)
   ↓
VALIDATOR
   ↓
DATA STORE → CATALOG → GEODATA INTERFACE
```

Frontera clave: el Connector produce **Source Representation** (no el objeto
normalizado V1.0). La normalización ocurre aguas abajo.

## 4. Connector Base

Interfaz mínima (no artificialmente grande):

```python
class BaseConnector:
    source: str                     # identificador de fuente
    capabilities: set[str]          # capacidades declaradas

    def discover(self, query: DiscoveryQuery) -> list[SourceReference]
    def get_metadata(self, ref: SourceReference) -> SourceMetadata
    def download(self, ref: SourceReference, dest: Path) -> DownloadedResource
    def verify(self, resource: DownloadedResource) -> bool
```

Cada conector: identifica fuente/producto, busca observaciones, selecciona
recursos, obtiene metadata, recupera datos, verifica integridad, reporta errores
y conserva provenance.

## 5. Source Representation

Objeto intermedio común entre Connector y Normalizer (representa la **fuente
original**, no el contrato V1.0):

```
{
  source, product, source_id, source_metadata,
  acquisition, spatial, temporal,
  resource, checksum, provenance
}
```

Diferencia con el contrato: el Source Representation conserva la metadata y los
formatos del proveedor; el Normalizer lo transforma al contrato V1.0.

## 6. Discovery

`DiscoveryQuery`: producto, intervalo temporal, AOI, tile/granule, resolución,
colección, calidad (si disponible). Las fuentes **no** están obligadas a soportar
todos los filtros; las capacidades se declaran (ver §15).

## 7. Authentication

Modos: público/anónimo, API key, OAuth/token, credenciales futuras. Reglas:
nunca secretos en código; nunca tokens en logs; configuración externa (variables
de entorno o `config/settings.json`, excluido por `.gitignore`); errores de
autenticación explícitos.

## 8. Download

Comportamiento común: timeout, retry con backoff, errores HTTP, rate limiting,
interrupción, descarga parcial, reanudación (cuando el proveedor lo permita),
checksum y detección de archivo corrupto.

## 9. Retry / errores

Clasificación de errores:

| Tipo | Clase | Retry |
|---|---|---|
| TRANSIENT (timeout, 5xx, rate limit) | `DownloadError`/`RateLimitError` | SÍ (backoff) |
| PERMANENT (404, auth, inválido) | `NotFoundError`/`AuthenticationError`/`IntegrityError` | NO |
| AUTH | `AuthenticationError` | NO (re-configurar) |
| NOT FOUND | `NotFoundError` | NO |
| RATE LIMIT | `RateLimitError` | SÍ (respetar `retry-after`) |
| INVALID RESOURCE | `IntegrityError` | NO |

## 10. Cache / Staging

```
SOURCE CACHE  →  STAGING  →  NORMALIZER
```

El Connector nunca escribe directamente en `normalized/`; usa staging y escritura
atómica. Una descarga incompleta nunca se considera un dataset válido.

## 11. Provenance

Conserva: `provider`, `source_url`, `collection/product`, `source_id`,
`retrieval_time`, `original_filename`, `version`, `checksum`, `license` (si está),
metadata original y el historial inicial de transformaciones. No se pierde
metadata del proveedor.

## 12. Errors (jerarquía)

```
ConnectorError
├── DiscoveryError
├── AuthenticationError
├── RateLimitError
├── DownloadError
├── IntegrityError
├── NotFoundError
├── MetadataError
└── UnsupportedProductError
```

Errores identificables, registrables, recuperables cuando corresponde, y con
distinción transitorio/permanente.

## 13. Logging

Estructurado para reconstruir: fuente, producto, recurso, operación, cuándo,
resultado, error, duración. Nunca se registran passwords, API keys ni tokens.
Evitar logs excesivos.

## 14. Rate limiting

Soporte para requests/minuto, concurrencia, límites del proveedor, `retry-after`
y throttling. No se asume que todas las fuentes tienen las mismas reglas.

## 15. Capabilities

Cada conector declara: `discovery`, `spatial_filter`, `temporal_filter`,
`tile_filter`, `metadata`, `download`, `streaming`, `authentication`, `resume`,
`checksum`. El motor consulta estas capacidades sin hardcodear lógica.

## 16. Product Adapters

Decisión: **SÍ** separar un **Product Adapter** delgado entre Connector y Source
Representation. Los productos STAC comparten transporte y discovery; el adapter
interpreta la metadata específica del producto. Para fuentes HTTP/file simples el
adapter es trivial o se omite.

## 17. Tipos de conector

- **STAC / Catalog API** — Copernicus Data Space, Landsat STAC, etc.
- **HTTP / API** — fuentes REST/HTTP.
- **File / Granule** — fuentes que entregan archivos/granules.
- **Scientific Data Service** — NetCDF/Zarr/multidimensional (ERA5-Land CDS).
- **Future authenticated** — credenciales futuras.

## 18. Configuración

Externa: endpoints, productos, timeout, retry, cache, paths, referencias de
autenticación, user-agent, límites de descarga. Separación estricta:
`código | configuración | secretos`.

## 19. Testabilidad

Permite mock HTTP, fixtures de metadata y recursos, timeout simulado, 429, 404,
archivo corrupto y fallo de autenticación. Los tests no dependen de Internet.

## 20. Primer conector recomendado (S-A.6)

**Sentinel-2 L2A (Copernicus Data Space).**

Justificación:
- Máximo valor agrícola (10 m, ~5 días, NDVI/vegetación).
- Ejercita la arquitectura completa: discovery STAC + descarga COG + raster multibanda.
- Acceso abierto (CC-BY), cobertura global incl. Sinaloa.
- Alternativas descartadas: Landsat (30 m, 16 días — igual de sólido pero menor
  resolución), Sentinel-1 (SAR, más complejo), ERA5-Land (NetCDF vía CDS, auth y
  reanálisis, menos directo para raster óptico).

## 21. Riesgos

- Acoplar el conector al formato de un proveedor (mitigado con Source Representation).
- Autenticación/rate-limit de CDS sin manejo correcto (mitigado con el error model).
- Descarga de tiles grandes sin límite de tamaño (mitigado con config de límites).

## 22. Siguiente fase

**S-A.6 — First Production Connector (Sentinel-2 L2A)**, sobre esta arquitectura.
