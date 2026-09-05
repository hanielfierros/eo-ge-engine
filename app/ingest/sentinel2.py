"""Ingesta minima Sentinel-2 L2A (S-A.15 / S-A.15.1).

Materializa assets espectrales en LocalDataStore, verifica integridad y los
registra en el Catalog. Un Item (deterministic_id) puede acumular varios
assets (B04, B08, ...). No calcula indices, no aplica scaling y no
reproyecta al CRS de analisis.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.catalog.adapter import normalized_to_item
from app.catalog.catalog import Catalog
from app.connectors.base import IntegrityError, NotFoundError, SourceReference, sha256_file
from app.connectors.sentinel2 import (
    Sentinel2L2AConnector,
    declared_raster_metadata,
    resolve_official_https_href,
)
from app.geodata.interface import GeoDataInterface
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.storage.base import FileMetadata
from app.storage.local import LocalDataStore
from app.validators.sentinel2 import Sentinel2Validator

JP2_SIGNATURE = b"\x00\x00\x00\x0cjP  \r\n\x87\n"
J2K_CODESTREAM = b"\xff\x4f\xff\x51"

COLLECTION = {
    "id": "sentinel-2-l2a",
    "title": "Sentinel-2 Level-2A",
    "description": "Sentinel-2 surface reflectance",
    "platform": "sentinel-2",
    "product": "S2MSI2A",
    "version": "1",
}

PREFERRED_BAND_ASSETS = ("B04_10m", "B08_10m", "B11_20m", "B04", "B08", "B11")


@dataclass
class IngestResult:
    product_id: str
    item_id: str
    asset_id: str
    href: str
    source: str
    acquisition_datetime: str | None
    tile: str | None
    processing_level: str | None
    checksum: str
    checksum_verification: str
    size_bytes: int
    storage_path: str
    catalog_id: str
    reused: bool
    raster_check: dict[str, Any] = field(default_factory=dict)
    declared_raster: dict[str, Any] = field(default_factory=dict)
    validation_status: str | None = None
    source_cache_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "item_id": self.item_id,
            "asset_id": self.asset_id,
            "href": self.href,
            "source": self.source,
            "acquisition_datetime": self.acquisition_datetime,
            "tile": self.tile,
            "processing_level": self.processing_level,
            "checksum": self.checksum,
            "checksum_verification": self.checksum_verification,
            "size_bytes": self.size_bytes,
            "storage_path": self.storage_path,
            "catalog_id": self.catalog_id,
            "reused": self.reused,
            "raster_check": self.raster_check,
            "declared_raster": self.declared_raster,
            "validation_status": self.validation_status,
            "source_cache_path": self.source_cache_path,
        }


def looks_like_jp2(path: Path) -> bool:
    try:
        header = path.read_bytes()[:16]
    except OSError:
        return False
    return header.startswith(JP2_SIGNATURE) or header.startswith(J2K_CODESTREAM)


def select_ingest_asset(assets: dict[str, Any], preferred: str | None = "B04_10m") -> str:
    if preferred and preferred in assets:
        return preferred
    for name in PREFERRED_BAND_ASSETS:
        if name in assets:
            return name
    raise NotFoundError("no hay asset espectral compatible para ingesta minima")


def _item_assets_from_collection(collection_metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not collection_metadata:
        return {}
    if "item_assets" in collection_metadata and isinstance(collection_metadata["item_assets"], dict):
        return collection_metadata["item_assets"]
    return collection_metadata


def _suffix_for_asset(asset: dict[str, Any], asset_name: str) -> str:
    media = str(asset.get("type") or "").lower()
    if "jp2" in media or "jpeg2000" in media:
        return ".jp2"
    if "tif" in media:
        return ".tif"
    href = str(asset.get("href") or "")
    suffix = Path(href.split("?")[0]).suffix
    if suffix and suffix.lower() in {".jp2", ".tif", ".tiff", ".xml", ".json"}:
        return suffix.lower()
    name_suffix = Path(asset_name).suffix
    return name_suffix or ".bin"


def _band_name(asset_name: str) -> str:
    match = re.match(r"^(B\d{2}|B8A)_", asset_name)
    return match.group(1) if match else asset_name


def _merge_normalized_metadata(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Fusiona bandas del incoming en metadata existente. Conserva identity y archivos."""
    if existing.get("identity", {}).get("id") != incoming.get("identity", {}).get("id"):
        raise IntegrityError("deterministic_id distinto; no se fusiona metadata")
    merged = copy.deepcopy(existing)
    bands: dict[str, dict[str, Any]] = {}
    raster = (merged.get("data") or {}).setdefault("raster", {})
    for band in raster.get("bands") or []:
        name = band.get("name")
        if name:
            bands[name] = band
    for band in ((incoming.get("data") or {}).get("raster") or {}).get("bands") or []:
        name = band.get("name")
        if name and name not in bands:
            bands[name] = band
    raster["bands"] = [bands[k] for k in sorted(bands)]
    dims = raster.get("dimensions")
    if isinstance(dims, dict):
        dims["band"] = len(raster["bands"])
    return merged


def ingest_sentinel2_asset(
    ref: SourceReference,
    store: LocalDataStore,
    catalog: Catalog,
    asset_name: str | None = "B04_10m",
    connector: Sentinel2L2AConnector | None = None,
    collection_metadata: dict[str, Any] | None = None,
    require_jp2_magic: bool = True,
) -> IngestResult:
    """Descarga, verifica y cataloga un asset sin destruir assets previos del Item.

    S-A.15.1: ingestión incremental. store.delete() no se usa cuando el producto
    ya existe. B04 + B08 coexisten bajo el mismo deterministic_id.
    """
    connector = connector or Sentinel2L2AConnector()
    assets = ref.item.get("assets") or {}
    asset_name = select_ingest_asset(assets, asset_name)
    asset = assets[asset_name]
    href = resolve_official_https_href(asset, asset_name)

    if collection_metadata is None:
        try:
            collection_metadata = connector.get_collection()
        except Exception:
            collection_metadata = {}
    item_assets = _item_assets_from_collection(collection_metadata)
    filtered_collection = {asset_name: item_assets[asset_name]} if asset_name in item_assets else item_assets

    work_item = dict(ref.item)
    work_item["assets"] = {asset_name: asset}
    work_ref = SourceReference(source_id=ref.source_id, collection=ref.collection, item=work_item)

    suffix = _suffix_for_asset(asset, asset_name)
    cache_dir = store.source_cache / ref.source_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{asset_name}{suffix}"
    if dest.is_file() and dest.stat().st_size == 0:
        dest.unlink()
    elif dest.is_file() and require_jp2_magic and suffix == ".jp2" and not looks_like_jp2(dest):
        dest.unlink()
    existed = dest.is_file() and dest.stat().st_size > 0
    prior_sha = sha256_file(dest) if existed else None

    resource = connector.download(work_ref, dest, asset_name=asset_name)
    reused = bool(existed and prior_sha and prior_sha == resource.checksum)

    if require_jp2_magic and suffix == ".jp2" and not looks_like_jp2(resource.path):
        resource.path.unlink(missing_ok=True)
        raise IntegrityError("contenido no es JPEG2000/JP2 valido")

    if resource.size_bytes <= 0:
        resource.path.unlink(missing_ok=True)
        raise IntegrityError("archivo descargado vacio")

    representation = connector.build_source_representation(
        work_ref, resource, collection_metadata=filtered_collection
    )
    metadata = Sentinel2L2ANormalizer().normalize(representation)
    result = Sentinel2Validator().validate(metadata)
    if result.status == "INVALID":
        raise IntegrityError("producto INVALID; no se almacena ni cataloga")
    pid = metadata["identity"]["id"]
    relative = f"{asset_name}{suffix}"
    stored_size = resource.size_bytes
    stored_sha = resource.checksum
    stored_media = asset.get("type") or "image/jp2"
    stored_format = "JP2" if suffix == ".jp2" else suffix.lstrip(".").upper()

    existing_file = store.get_file(pid, relative) if store.exists(pid) else None
    this_ok = bool(
        existing_file is not None
        and existing_file.is_file()
        and sha256_file(existing_file) == resource.checksum
    )
    product_ok = bool(store.exists(pid) and store.verify(pid))

    if store.exists(pid) and this_ok and product_ok:
        reused = True
        stored_size = existing_file.stat().st_size
        stored_sha = resource.checksum
        existing_meta = store.get_metadata(pid) or metadata
        metadata = _merge_normalized_metadata(existing_meta, metadata)
        if metadata != existing_meta:
            store.update_metadata(pid, metadata)
    elif store.exists(pid):
        # Incremental: NUNCA borrar el producto. Solo anade/reemplaza este asset.
        if not this_ok:
            file_meta = FileMetadata(
                filename=relative,
                relative_path=relative,
                media_type=stored_media,
                role="data",
                format=stored_format,
                source_generated="source",
            )
            stored = store.put_file(pid, file_meta, resource.path)
            if stored.sha256 and stored.sha256 != resource.checksum:
                raise IntegrityError("checksum del Data Store no coincide con el de descarga")
            stored_size = stored.size
            stored_sha = stored.sha256
            stored_media = stored.media_type or stored_media
            stored_format = stored.format or stored_format
        existing_meta = store.get_metadata(pid) or metadata
        metadata = _merge_normalized_metadata(existing_meta, metadata)
        store.update_metadata(pid, metadata)
    else:
        store.put_metadata(pid, metadata)
        file_meta = FileMetadata(
            filename=relative,
            relative_path=relative,
            media_type=stored_media,
            role="data",
            format=stored_format,
            source_generated="source",
        )
        stored = store.put_file(pid, file_meta, resource.path)
        if stored.sha256 and stored.sha256 != resource.checksum:
            raise IntegrityError("checksum del Data Store no coincide con el de descarga")
        stored_size = stored.size
        stored_sha = stored.sha256
        stored_media = stored.media_type or stored_media
        stored_format = stored.format or stored_format

    storage_path = f"normalized/{pid}"
    file_href = f"{storage_path}/files/{relative}"
    catalog.register_collection(COLLECTION)
    materialized_key = _band_name(asset_name)
    asset_record = {
        "asset_key": asset_name,
        "href": file_href,
        "media_type": stored_media,
        "role": "data",
        "title": asset_name,
        "size": stored_size,
        "checksum": stored_sha,
        "format": stored_format,
    }
    item = normalized_to_item(
        metadata,
        storage_path=storage_path,
        materialized_files={materialized_key: asset_record},
    )
    if not catalog.exists(pid):
        catalog.register_item(item)
    else:
        catalog.register_asset(pid, asset_record)

    geo = GeoDataInterface(catalog, store)
    if not geo.exists(pid):
        raise IntegrityError("item no recuperable tras catalogar")
    retrieved = geo.get_file(pid, relative)
    if not retrieved.is_file():
        raise IntegrityError("archivo fisico ausente tras catalogar")
    if sha256_file(retrieved) != resource.checksum:
        raise IntegrityError("checksum de recuperacion no coincide")
    if not geo.verify(pid):
        raise IntegrityError("Data Store verify() fallo tras catalogar")

    props = ref.item.get("properties") or {}
    raster_check = {
        "format_ok": looks_like_jp2(resource.path) if suffix == ".jp2" else True,
        "magic": "JP2" if suffix == ".jp2" else suffix.lstrip("."),
        "size_bytes": resource.size_bytes,
        "opened_with_rasterio": False,
        "scaling_applied": False,
    }
    declared = declared_raster_metadata(asset)
    if not declared.get("proj_code"):
        spatial = metadata.get("spatial") or {}
        if spatial.get("crs"):
            declared["proj_code"] = spatial["crs"]
        if spatial.get("epsg") is not None:
            declared["proj_epsg"] = spatial["epsg"]

    return IngestResult(
        product_id=ref.source_id,
        item_id=pid,
        asset_id=asset_name,
        href=href,
        source=representation.source,
        acquisition_datetime=props.get("datetime") or representation.acquisition.get("observation_time"),
        tile=(representation.spatial or {}).get("tile") or props.get("grid:code"),
        processing_level=props.get("processing:level") or representation.acquisition.get("processing_level"),
        checksum=resource.checksum or stored.sha256 or "",
        checksum_verification=resource.checksum_verification or "SHA-256_LOCAL",
        size_bytes=resource.size_bytes,
        storage_path=str(retrieved),
        catalog_id=pid,
        reused=reused,
        raster_check=raster_check,
        declared_raster=declared,
        validation_status=result.status,
        source_cache_path=str(resource.path),
    )
