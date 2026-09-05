# EO-GE GeoData Interface (S-A.11)

## Propósito

Fachada interna read-oriented sobre **Catalog** + **Data Store** para consultar
y recuperar productos normalizados con una interfaz única, sin API web,
frontend, mapas ni procesamiento científico.

## Posición arquitectónica

```
Application / Future Engine
   ↓
GeoData Interface
   ├── Catalog      (search / items / assets)
   └── Data Store   (metadata / files / verify)
```

## Dependencias

- `Catalog` (app/catalog) para búsqueda e items.
- `DataStore` (app/storage) para metadata, archivos e integridad.

## Métodos

- `search(...)` — delega al Catalog (filtros: collection, datetime, rango, platform, product, validation_status, bbox).
- `get_item(id)` — item por deterministic_id (ItemNotFoundError).
- `get_metadata(id)` — metadata normalizada (MetadataNotFoundError), sin reinterpretar.
- `get_asset(id, key)` — referencia de asset (AssetNotFoundError).
- `get_file(id, relative_path)` — ruta del archivo (StorageReferenceError); no carga el archivo en memoria.
- `exists(id)` — delegado al Data Store.
- `verify(id)` — integridad delegada al Data Store.

## Flujo Catalog / Data Store

La búsqueda y los items vienen del Catalog; metadata, archivos e integridad del
Data Store. La interfaz solo coordina y resuelve referencias.

## Errores

`GeoDataError` → `ItemNotFoundError`, `AssetNotFoundError`,
`MetadataNotFoundError`, `StorageReferenceError`.

## Seguridad

Read-only; no modifica archivos ni metadata; delega path safety al Data Store
(rechaza `../` y rutas absolutas); no introduce SQL propia.

## Limitaciones

- Sin streaming HTTP ni API pública.
- Sin list_collections (no requerido en esta fase).
- Read-oriented: no hay métodos de escritura.

## Ejemplo conceptual

```python
from app.geodata.interface import GeoDataInterface

geo = GeoDataInterface(catalog, store)
items = geo.search(collection="sentinel-2-l2a", bbox=(-108.6, 25.4, -108.3, 25.7))
item = geo.get_item(items[0]["id"])
meta = geo.get_metadata(item["id"])
asset = geo.get_asset(item["id"], "metadata")
path = geo.get_file(item["id"], "B04_10m.jp2")
ok = geo.verify(item["id"])
```

## Qué NO hace

No normaliza, no valida científicamente, no descarga, no reproyecta, no calcula
NDVI/índices, no hace análisis raster/vectorial ni interpretación.
