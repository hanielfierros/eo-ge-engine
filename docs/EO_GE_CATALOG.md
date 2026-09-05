# EO-GE Catalog (S-A.10)

## Propósito

Indexar y permitir descubrir los productos normalizados. El Data Store conserva
los datos; el Catalog los indexa.

## Relación Data Store / Catalog

El Catalog deriva del producto normalizado (via Catalog Adapter), sin crear
metadata científica paralela. Conserva referencia al `deterministic_id` y al
`storage_path`.

## Modelo STAC

`Catalog → Collection → Item → Assets`, compatible conceptualmente con STAC. No
se implementa un STAC API completo. Los campos EO-GE sin equivalente STAC se
guardan en `properties`.

## SQLite

`catalog/eo_ge_catalog.sqlite` (gitignored). Tablas `catalog_metadata`,
`collections`, `items`, `assets` + índices.

## Collections

`id`, `title`, `description`, `platform`, `product`, `version`, timestamps.

## Items

`id` (deterministic_id), `collection_id`, `source_id`, `product`, `platform`,
`instrument`, `processing_level`, `datetime`, `start/end_datetime`, `geometry`
(GeoJSON), `bbox`, `cloud_cover`, `validation_status`, `storage_path`,
`properties` (JSON), timestamps.

## Assets

`item_id`, `asset_key`, `href`, `media_type`, `role`, `title`, `size`,
`checksum`, `format`.

## Búsquedas

`search()` con filtros: collection, datetime, rango temporal, platform, product,
validation_status y bbox (intersección controlada en Python, no PostGIS).

## Identidad

`deterministic_id` como `id` del Item. Un mismo producto → mismo Item.

## Idempotencia

Registrar el mismo producto dos veces no genera duplicados. Si el contenido
esencial cambia con el mismo id → `CATALOG_ID_CONFLICT`.

## Transacciones

`register_item` inserta Item + Assets en una transacción con rollback ante
error; nunca queda un Item parcialmente registrado.

## Path safety

Se rechazan `../`, rutas absolutas, letras de unidad y rutas vacías en
`storage_path` y `href` de assets.

## Limitaciones

- SQLite local; sin PostgreSQL/PostGIS/STAC API/cloud.
- Búsqueda espacial MVP por bbox (no geoprocesamiento).
- No almacena arrays raster en SQLite.

## Migración futura

A PostgreSQL/PostGIS/STAC API sin cambiar Connector/Normalizer/Data Store.
