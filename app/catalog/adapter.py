"""Adapter: producto normalizado (contrato V1.0) -> Item STAC-compatible (S-A.10)."""

from __future__ import annotations

from typing import Any


def normalized_to_item(
    metadata: dict[str, Any],
    storage_path: str | None = None,
    materialized_files: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convierte un producto normalizado EO-GE en un Item tipo STAC.

    No modifica el metadata.json; solo deriva la representacion de catalogo.
    `materialized_files` asocia asset_key -> {href, media_type, size, checksum, format}
    para assets fisicamente almacenados. Sin ello, las bandas quedan sin href.
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

    assets = _build_assets(metadata, storage_path, materialized_files)

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


def _build_assets(
    metadata: dict[str, Any],
    storage_path: str | None,
    materialized_files: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    materialized = dict(materialized_files or {})
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
    used_keys: set[str] = set()
    for b in bands:
        name = b.get("name")
        mat = None
        if name in materialized:
            mat = materialized[name]
            used_keys.add(name)
        asset = {
            "asset_key": name,
            "href": None,
            "media_type": None,
            "role": "data",
            "title": name,
            "format": storage.get("format"),
        }
        if mat:
            asset.update({k: v for k, v in mat.items() if v is not None})
            asset["asset_key"] = mat.get("asset_key") or name
            asset["role"] = mat.get("role") or "data"
        assets.append(asset)

    for key, mat in materialized.items():
        if key in used_keys:
            continue
        if any(a.get("asset_key") == key for a in assets):
            continue
        extra = {
            "asset_key": key,
            "href": None,
            "media_type": None,
            "role": mat.get("role") or "data",
            "title": mat.get("title") or key,
        }
        extra.update({k: v for k, v in mat.items() if v is not None})
        assets.append(extra)
    return assets
