"""Adapter: producto normalizado (contrato V1.0) -> Item STAC-compatible (S-A.10)."""

from __future__ import annotations

from typing import Any


def normalized_to_item(metadata: dict[str, Any], storage_path: str | None = None) -> dict[str, Any]:
    """Convierte un producto normalizado EO-GE en un Item tipo STAC.

    No modifica el metadata.json; solo deriva la representacion de catalogo.
    """
    identity = metadata.get("identity", {})
    source = metadata.get("source", {})
    product = metadata.get("product", {})
    acquisition = metadata.get("acquisition", {})
    spatial = metadata.get("spatial", {})
    quality = metadata.get("quality", {})
    provenance = metadata.get("provenance", {})

    dataset_quality = quality.get("dataset_quality") or {}
    cloud_cover = dataset_quality.get("cloud_cover_percent")

    assets = _build_assets(metadata, storage_path)

    return {
        "id": identity.get("id"),
        "collection_id": source.get("collection"),
        "source_id": provenance.get("original_product"),
        "product": product.get("product"),
        "platform": source.get("platform"),
        "instrument": source.get("instrument"),
        "processing_level": product.get("processing_level"),
        "datetime": acquisition.get("observation_time"),
        "start_datetime": acquisition.get("start_time"),
        "end_datetime": acquisition.get("end_time"),
        "geometry": spatial.get("footprint"),
        "bbox": spatial.get("bounds"),
        "cloud_cover": cloud_cover,
        "validation_status": quality.get("status"),
        "storage_path": storage_path,
        "properties": {
            "data_class": metadata.get("data_class"),
            "provider": source.get("provider"),
            "product_type": product.get("product_type"),
            "crs": spatial.get("crs"),
            "epsg": spatial.get("epsg"),
        },
        "assets": assets,
    }


def _build_assets(metadata: dict[str, Any], storage_path: str | None) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    if storage_path:
        assets.append({
            "asset_key": "metadata",
            "href": f"{storage_path}/metadata.json",
            "media_type": "application/json",
            "role": "metadata",
            "title": "metadata.json",
        })

    data = metadata.get("data", {})
    storage = data.get("storage", {}) or {}
    bands = (data.get("raster") or {}).get("bands", [])
    for b in bands:
        assets.append({
            "asset_key": b.get("name"),
            "href": None,  # el raster no esta materializado aun
            "media_type": None,
            "role": "data",
            "title": b.get("name"),
            "format": storage.get("format"),
        })
    return assets
