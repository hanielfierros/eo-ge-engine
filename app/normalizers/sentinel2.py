"""Normalizador Sentinel-2 L2A (S-A.7).

Transforma una SourceRepresentation producida por Sentinel2L2AConnector en un
objeto compatible con el contrato EO-GE NORMALIZED DATA CONTRACT V1.0.

Regla cientifica: normalizar NO es simplificar; se conserva toda la metadata
disponible y la ausencia de un dato se representa sin inventar valores.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import SourceRepresentation
from app.normalizers.base import BaseNormalizer, NormalizationError

CONTRACT_NAME = "EO_GE_NORMALIZED_DATA_CONTRACT"
CONTRACT_VERSION = "1.0"
SOURCE_TOKEN = "SENTINEL2"
DATA_CLASS = "SCIENTIFIC_PRODUCT"
PROCESSING_LEVEL = "L2A"

# Bandas espectrales Sentinel-2 (B01..B12 y B8A) por resolucion.
_BAND_RE = re.compile(r"^(B\d{2}|B8A)_(10m|20m|60m)$")
_RES_RANK = {"10m": 3, "20m": 2, "60m": 1}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact_datetime(value: str | None) -> str | None:
    if not value:
        return None
    s = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(s).strftime("%Y%m%dT%H%M%S")
    except ValueError:
        return None


def _epsg_from_tile(tile: str | None) -> int | None:
    """Deriva EPSG UTM desde el tile MGRS (p. ej. 'T12RYP' -> 32612)."""
    if not tile or len(tile) < 4:
        return None
    zone, band = tile[1:3], tile[3]
    if zone.isdigit() and band.isalpha():
        z = int(zone)
        return (32600 if band.upper() >= "N" else 32700) + z
    return None


def _deterministic_id(sr: SourceRepresentation, tile: str | None) -> str:
    product = sr.source_metadata.get("properties", {}).get("product:type") or "S2MSI2A"
    dt = _compact_datetime(sr.acquisition.get("observation_time")) or "UNKNOWN"
    parts = [SOURCE_TOKEN, product, dt]
    if tile:
        parts.append(tile)
    parts.append("v1")
    return "_".join(parts)


def _build_bands(sr: SourceRepresentation) -> list[dict[str, Any]]:
    item_assets = sr.source_metadata.get("assets", {})
    collection_assets = sr.collection_metadata or {}

    # Agrupar por banda (B04) conservando la mayor resolucion.
    grouped: dict[str, tuple[str, str]] = {}
    for key in item_assets:
        m = _BAND_RE.match(key)
        if not m:
            continue
        band, res = m.group(1), m.group(2)
        if band not in grouped or _RES_RANK[res] > _RES_RANK[grouped[band][0]]:
            grouped[band] = (res, key)

    if not grouped:
        raise NormalizationError("no se encontraron bandas espectrales en la Source Representation")

    bands: list[dict[str, Any]] = []
    for band in sorted(grouped):
        res, key = grouped[band]
        ia = item_assets.get(key, {})
        ca = collection_assets.get(key, {})
        common_name = None
        for entry in (ia.get("bands") or []) + (ca.get("bands") or []):
            if entry.get("eo:common_name"):
                common_name = entry["eo:common_name"]
        dtype = ca.get("data_type")
        if dtype is None:
            raise NormalizationError(f"banda {band} sin dtype en la metadata de coleccion")
        bands.append({
            "name": band,
            "variable": common_name,
            "units": None,
            "dtype": dtype,
            "scale": ca.get("raster:scale"),
            "offset": ca.get("raster:offset"),
            "nodata": ca.get("nodata"),
        })
    return bands


def _build_dimensions(sr: SourceRepresentation) -> dict[str, Any] | None:
    item_assets = sr.source_metadata.get("assets", {})
    collection_assets = sr.collection_metadata or {}
    for key, ia in item_assets.items():
        m = _BAND_RE.match(key)
        if not m:
            continue
        shape = ia.get("proj:shape") or collection_assets.get(key, {}).get("proj:shape")
        if shape and len(shape) >= 2:
            return {"x": int(shape[1]), "y": int(shape[0])}
    return None


class Sentinel2L2ANormalizer(BaseNormalizer):
    """Normalizador Sentinel-2 L2A -> contrato V1.0."""

    source = "COPERNICUS_DATA_SPACE"
    product = "SENTINEL2_L2A"

    def normalize(self, sr: SourceRepresentation) -> dict[str, Any]:
        if sr.product != self.product:
            raise NormalizationError(f"producto incompatible: {sr.product!r} (esperado {self.product!r})")

        props = sr.source_metadata.get("properties", {})
        tile = sr.spatial.get("tile")
        epsg = sr.spatial.get("epsg") or _epsg_from_tile(tile)
        bounds = sr.spatial.get("bbox") or sr.source_metadata.get("bbox")
        geometry = sr.spatial.get("geometry") or sr.source_metadata.get("geometry")
        gsd = sr.spatial.get("gsd")

        if epsg is None:
            raise NormalizationError("no se pudo determinar el CRS (proj:epsg ausente y tile sin zona UTM)")
        if not bounds:
            raise NormalizationError("no se pudo determinar bounds (bbox ausente)")

        identity_id = _deterministic_id(sr, tile)

        bands = _build_bands(sr)
        dimensions = _build_dimensions(sr)
        if dimensions is not None:
            dimensions["band"] = len(bands)

        cloud_cover = props.get("eo:cloud_cover")
        dataset_quality: dict[str, Any] = {}
        if cloud_cover is not None:
            dataset_quality["cloud_cover_percent"] = float(cloud_cover)

        output: dict[str, Any] = {
            "contract": {
                "name": CONTRACT_NAME,
                "version": CONTRACT_VERSION,
                "schema_version": CONTRACT_VERSION,
            },
            "identity": {
                "id": identity_id,
                "version": "v1",
            },
            "data_class": DATA_CLASS,
            "source": {
                "provider": "ESA",
                "mission": "Sentinel-2",
                "platform": props.get("platform"),
                "instrument": (props.get("instruments") or [None])[0],
                "collection": sr.source_metadata.get("collection") or sr.provenance.get("collection"),
            },
            "product": {
                "product": props.get("product:type") or "S2MSI2A",
                "product_type": "Surface Reflectance",
                "processing_level": PROCESSING_LEVEL,
                "version": None,
            },
            "acquisition": {
                "start_time": sr.acquisition.get("start_time") or props.get("start_datetime") or props.get("datetime"),
                "end_time": sr.acquisition.get("end_time") or props.get("end_datetime"),
                "observation_time": sr.acquisition.get("observation_time") or props.get("datetime"),
            },
            "spatial": {
                "crs": f"EPSG:{epsg}" if epsg else None,
                "native_crs": f"EPSG:{epsg}" if epsg else None,
                "epsg": epsg,
                "bounds": bounds,
                "geometry_type": geometry.get("type") if isinstance(geometry, dict) else None,
                "footprint": geometry,
                "resolution": {"x": gsd, "y": gsd, "unit": "m"} if gsd else None,
                "width": None,
                "height": None,
                "tile": tile,
            },
            "data": {
                "kind": "raster",
                "raster": {
                    "bands": bands,
                    "dimensions": dimensions,
                    "qa_band": "SCL",
                    "cloud_mask": "SCL",
                },
                "storage": {
                    "format": "COG",
                    "asset_id": identity_id,
                    "checksum": sr.checksum,
                },
            },
            "quality": {
                "status": "AVAILABLE",
                "dataset_quality": dataset_quality,
            },
            "provenance": {
                "source_url": sr.resource.get("source_url") or sr.provenance.get("source_url"),
                "provider": sr.provenance.get("provider"),
                "original_product": sr.source_id,
                "download_time": sr.provenance.get("retrieval_time"),
                "processing_time": _utc_iso(),
                "processing_software": "EO-GE ENGINE",
                "processing_version": "0.7",
                "transformations": [],
                "checksum": sr.checksum,
                "license": sr.provenance.get("license"),
                "citation": props.get("sci:citation"),
                "parent_dataset": None,
            },
        }

        # Eliminar claves con valor None donde el schema usa additionalProperties:false
        # (las claves opcionales pueden omitirse, no ponerse en null).
        output = _prune_nulls(output)
        return output


def _prune_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _prune_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_prune_nulls(v) for v in obj]
    return obj
