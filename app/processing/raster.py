"""Procesamiento raster cientifico (S-A.16).

JP2 Sentinel-2 L2A (DN uint16) -> reflectancia superficial float32 con mascara de
nadata y salida COG real.

Reglas cientificas:
  - reflectancia = DN * SCALE + OFFSET, con SCALE = 0.0001, OFFSET = -0.1
    (Sentinel-2 L2A baseline >= 04.00).
  - DN == 0 es pixel invalido (nadata/edge) y se convierte a NaN (float32).
  - DN > 10000 es esperado (NO se corrige ni se recorta).
  - CRS nativo EPSG:32612 conservado (sin reproyeccion).
  - Fuente JP2 intacta (solo lectura).

Reutiliza LocalDataStore (bucket `derived/`), Catalog y GeoDataInterface; no crea
una segunda arquitectura.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS

from app.catalog.adapter import normalized_to_item
from app.catalog.catalog import Catalog
from app.connectors.base import sha256_file
from app.geodata.interface import GeoDataInterface
from app.storage.base import FileMetadata, StorageConflictError
from app.storage.local import LocalDataStore

SCALE = 0.0001
OFFSET = -0.1
NODATA = float("nan")
NODATA_LABEL = "nan"

CONTRACT_NAME = "EO_GE_NORMALIZED_DATA_CONTRACT"
CONTRACT_VERSION = "1.0"
DATA_CLASS = "DERIVED_PRODUCT"
SOFTWARE = "EO-GE ENGINE"
SOFTWARE_VERSION = "0.7"

COLLECTION = {
    "id": "sentinel-2-l2a",
    "title": "Sentinel-2 Level-2A",
    "description": "Sentinel-2 surface reflectance",
    "platform": "sentinel-2",
    "product": "S2MSI2A",
    "version": "1",
}

# Perfil COG razonable y documentado: DEFLATE + bloques de 512 + overviews internas.
COG_OPTIONS = {"compress": "deflate", "blocksize": 512}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reflectance_from_dn(dn: np.ndarray) -> np.ndarray:
    """DN uint16 -> reflectancia float32 (sin mascara): DN * SCALE + OFFSET."""
    return dn.astype(np.float32) * SCALE + OFFSET


def build_valid_mask(dn: np.ndarray) -> np.ndarray:
    """Mascara valida: DN != 0 (DN == 0 es nodata/edge)."""
    return dn != 0


def apply_mask(array: np.ndarray, mask: np.ndarray, nodata: float = NODATA) -> np.ndarray:
    """Aplica la mascara invalida sobre la reflectancia float32."""
    out = array.astype(np.float32).copy()
    out[~mask] = nodata
    return out


def write_cog(
    path: Path,
    array: np.ndarray,
    crs: CRS,
    transform: Any,
    nodata: float = NODATA,
    compress: str = "deflate",
    blocksize: int = 512,
) -> Path:
    """Escribe un COG real (GeoTIFF Cloud-Optimized) con overviews internas."""
    height, width = array.shape[-2], array.shape[-1]
    profile = {
        "driver": "COG",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": compress,
        "blocksize": blocksize,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype("float32"), 1)
    return path


def _build_derived_metadata(
    source_meta: dict[str, Any],
    derived_id: str,
    band_name: str,
    band_variable: str,
    crs: str,
    epsg: int,
    bounds: list[float],
    transform: list[float],
    width: int,
    height: int,
    cog_sha256: str,
    processing_time: str,
    resolution: tuple[float, float] = (10.0, 10.0),
) -> dict[str, Any]:
    """Construye metadata de producto derivado conforme al contrato V1.0."""
    source = source_meta.get("source", {})
    product = source_meta.get("product", {})
    acquisition = source_meta.get("acquisition", {})
    spatial = source_meta.get("spatial", {})
    provenance = source_meta.get("provenance", {})

    dataset_quality = dict((source_meta.get("quality") or {}).get("dataset_quality") or {})

    metadata: dict[str, Any] = {
        "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION, "schema_version": CONTRACT_VERSION},
        "identity": {"id": derived_id, "version": "v1"},
        "data_class": DATA_CLASS,
        "source": source,
        "product": product,
        "acquisition": acquisition,
        "processing": {
            "processing_type": "DERIVED",
            "transformations": [
                "reflectance = DN * 0.0001 - 0.1 (Sentinel-2 L2A baseline>=04.00)",
                "nadata mask: DN == 0 -> NaN (float32)",
                "COG encoding: GeoTIFF COG, DEFLATE, blocksize 512, overviews internas",
            ],
        },
        "spatial": {
            "crs": crs,
            "native_crs": crs,
            "epsg": epsg,
            "bounds": bounds,
            "geometry_type": spatial.get("geometry_type"),
            "footprint": spatial.get("footprint"),
            "transform": transform,
            "resolution": {"x": resolution[0], "y": resolution[1], "unit": "m"},
            "width": width,
            "height": height,
            "tile": spatial.get("tile"),
        },
        "data": {
            "kind": "raster",
            "raster": {
                "bands": [
                    {
                        "name": band_name,
                        "variable": band_variable,
                        "units": "1",
                        "dtype": "float32",
                        "scale": 1.0,
                        "offset": 0.0,
                        "nodata": NODATA_LABEL,
                    }
                ],
                "dimensions": {"x": width, "y": height, "band": 1},
            },
            "storage": {
                "format": "COG",
                "asset_id": derived_id,
                "checksum": cog_sha256,
            },
        },
        "quality": {
            "status": "AVAILABLE",
            "dataset_quality": dataset_quality,
        },
        "provenance": {
            "source_url": provenance.get("source_url"),
            "provider": provenance.get("provider"),
            "original_product": provenance.get("original_product"),
            "download_time": provenance.get("download_time"),
            "processing_time": processing_time,
            "processing_software": SOFTWARE,
            "processing_version": SOFTWARE_VERSION,
            "transformations": [
                "reflectance = DN * 0.0001 - 0.1 (Sentinel-2 L2A baseline>=04.00)",
                "nadata mask: DN == 0 -> NaN (float32)",
                "COG encoding: GeoTIFF COG, DEFLATE, blocksize 512, overviews internas",
            ],
            "checksum": cog_sha256,
            "license": provenance.get("license"),
            "parent_dataset": (source_meta.get("identity") or {}).get("id"),
        },
    }
    return metadata


@dataclass
class DeriveResult:
    derived_id: str
    band: str
    variable: str
    relative_path: str
    cog_path: Path
    cog_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_id": self.derived_id,
            "band": self.band,
            "variable": self.variable,
            "relative_path": self.relative_path,
            "cog_path": str(self.cog_path),
            "cog_sha256": self.cog_sha256,
            "checks": self.checks,
        }


def _find_dn_locations(dn: np.ndarray, target: int, max_candidates: int = 1) -> list[tuple[int, int]]:
    """Ubica (fila, col) de píxeles con DN exacto == target."""
    ys, xs = np.where(dn == target)
    if len(ys) == 0:
        return []
    locs = [(int(y), int(x)) for y, x in zip(ys[:max_candidates], xs[:max_candidates])]
    return locs


def derive_band_reflectance(
    store: LocalDataStore,
    catalog: Catalog,
    source_item_id: str,
    source_rel_path: str,
    derived_id: str,
    band_name: str,
    band_variable: str,
    rel_name: str | None = None,
    resolution: tuple[float, float] | None = None,
) -> DeriveResult:
    """Deriva un producto de reflectancia (COG) a partir de un JP2 fuente.

    Solo lectura de la fuente. Escribe el COG en storage/derived/<id>/ y registra
    el producto en el catalogo. El nombre de archivo y la resolucion se derivan de
    la fuente por defecto; pueden sobrescribirse con `rel_name`/`resolution`
    (p. ej. B11_20m nativo 20 m).
    """
    geo = GeoDataInterface(catalog, store)
    src_path = geo.get_file(source_item_id, source_rel_path)
    source_meta = geo.get_metadata(source_item_id)

    with rasterio.open(src_path) as ds:
        crs = ds.crs
        epsg = ds.crs.to_epsg() if ds.crs else None
        width, height = ds.width, ds.height
        transform = ds.transform
        gdal_transform = list(ds.transform.to_gdal())  # [x0, px_w, rot, y0, rot, px_h]
        bounds = [float(ds.bounds.left), float(ds.bounds.bottom), float(ds.bounds.right), float(ds.bounds.top)]
        src_res = (float(ds.res[0]), float(ds.res[1]))
        dn = ds.read(1)

    valid = build_valid_mask(dn)
    refl = reflectance_from_dn(dn)
    refl = apply_mask(refl, valid)

    res = resolution or src_res
    rel = rel_name or f"{band_name}_10m_reflectance.tif"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cog = Path(tmpdir) / rel
        write_cog(tmp_cog, refl, crs, transform)
        cog_sha = sha256_file(tmp_cog)

        # Idempotencia: si ya existe el mismo contenido, reutilizar sin duplicar.
        if store.exists_derived(derived_id):
            existing_cog = store.get_derived_file(derived_id, rel)
            if existing_cog is not None and existing_cog.is_file() and sha256_file(existing_cog) == cog_sha:
                existing_meta = store.get_derived_metadata(derived_id)
                return DeriveResult(
                    derived_id=derived_id,
                    band=band_name,
                    variable=band_variable,
                    relative_path=rel,
                    cog_path=existing_cog,
                    cog_sha256=cog_sha,
                    metadata=existing_meta if existing_meta is not None else {},
                )
            raise StorageConflictError(f"producto derivado ya existe con contenido distinto: {derived_id}")

        processing_time = _utc_iso()
        metadata = _build_derived_metadata(
            source_meta=source_meta,
            derived_id=derived_id,
            band_name=band_name,
            band_variable=band_variable,
            crs=f"EPSG:{epsg}" if epsg else str(crs),
            epsg=epsg,
            bounds=bounds,
            transform=gdal_transform,
            width=width,
            height=height,
            cog_sha256=cog_sha,
            processing_time=processing_time,
            resolution=res,
        )

        store.put_derived_metadata(derived_id, metadata)
        file_meta = FileMetadata(
            filename=rel,
            relative_path=rel,
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            role="data",
            format="COG",
            source_generated="generated",
        )
        stored = store.put_derived_file(derived_id, file_meta, tmp_cog)

        # Catalogar.
        catalog.register_collection(COLLECTION)
        storage_path = f"derived/{derived_id}"
        asset_record = {
            "asset_key": band_name,
            "href": f"{storage_path}/files/{rel}",
            "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "role": "data",
            "title": rel,
            "size": stored.size,
            "checksum": cog_sha,
            "format": "COG",
        }
        item = normalized_to_item(metadata, storage_path=storage_path, materialized_files={band_name: asset_record})
        if not catalog.exists(derived_id):
            catalog.register_item(item)
        else:
            catalog.register_asset(derived_id, asset_record)

        final_cog = store.get_derived_file(derived_id, rel)
        if final_cog is None or sha256_file(final_cog) != cog_sha:
            raise RuntimeError("producto derivado no recuperable tras persistir")

    return DeriveResult(
        derived_id=derived_id,
        band=band_name,
        variable=band_variable,
        relative_path=rel,
        cog_path=final_cog,
        cog_sha256=cog_sha,
        metadata=metadata,
    )


def validate_derived_product(
    store: LocalDataStore,
    catalog: Catalog,
    source_item_id: str,
    source_rel_path: str,
    derived_id: str,
    relative_path: str,
    expected_crs_epsg: int,
    expected_width: int,
    expected_height: int,
    expected_res: tuple[float, float],
) -> list[dict[str, Any]]:
    """Valida un producto derivado (geométrica, numérica, máscara, COG, integridad)."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    geo = GeoDataInterface(catalog, store)
    src_path = geo.get_file(source_item_id, source_rel_path)
    cog_path = store.get_derived_file(derived_id, relative_path)

    check("file_exists", cog_path is not None and cog_path.is_file(), str(cog_path))
    if cog_path is None or not cog_path.is_file():
        return checks

    with rasterio.open(src_path) as src:
        src_transform = src.transform
        src_crs = src.crs
        src_width, src_height = src.width, src.height
        src_nodata = src.nodata
        dn = src.read(1)

    with rasterio.open(cog_path) as dst:
        dst_driver = dst.driver
        dst_crs = dst.crs
        dst_transform = dst.transform
        dst_width, dst_height = dst.width, dst.height
        dst_nodata = dst.nodata
        dst_dtype = dst.dtypes[0]
        dst_blocks = dst.block_shapes[0]
        dst_overviews = dst.overviews(1)
        dst_compress = dst.compression
        dst_tiled = dst_blocks[0] < dst_width or dst_blocks[1] < dst_height
        dst_res = dst.res
        refl = dst.read(1)

    check("opens_with_rasterio", True, f"driver={dst_driver}")
    check("crs_correct", dst_crs is not None and dst_crs.to_epsg() == expected_crs_epsg, str(dst_crs))
    check("transform_correct", dst_transform == src_transform, str(dst_transform))
    check(
        "resolution_correct",
        abs(dst_res[0] - expected_res[0]) < 1e-9 and abs(dst_res[1] - expected_res[1]) < 1e-9,
        str(dst_res),
    )
    check("dimensions_correct", dst_width == expected_width and dst_height == expected_height, f"{dst_width}x{dst_height}")
    check("aligned_with_source", dst_transform == src_transform and dst_width == src_width and dst_height == src_height, "")
    check("dtype_float32", dst_dtype == "float32", dst_dtype)
    check("nodata_is_nan", dst_nodata is not None and math.isnan(float(dst_nodata)), str(dst_nodata))

    valid_mask = build_valid_mask(dn)
    nan_mask = np.isnan(refl)
    n_invalid = int(np.count_nonzero(~valid_mask))
    n_nan = int(np.count_nonzero(nan_mask))
    check("mask_coherent", n_nan == n_invalid, f"source_invalid={n_invalid} cog_nan={n_nan}")

    check("dn0_not_valid_reflectance", bool(np.all(nan_mask[~valid_mask])), "")
    check("no_silent_transformation", not np.any(nan_mask[valid_mask]), "reflectancia valida sin NaN")
    check("no_silent_reprojection", dst_crs is not None and dst_crs.to_epsg() == src_crs.to_epsg(), str(dst_crs))

    # Valores de reflectancia numéricamente coherentes con la fórmula.
    n_valid = int(np.count_nonzero(valid_mask))
    check("no_unexpected_coverage_loss", n_valid > 0 and n_valid == int(np.count_nonzero(~nan_mask)), f"valid={n_valid}")

    # Muestra determinista (indices validos dentro del raster).
    sample_ok = True
    sample_detail = []
    h, w = dn.shape
    sample_points = [(0, 0), (0, 1), (1, 0), (h - 1, w - 1), (h // 2, w // 2)]
    for y, x in sample_points:
        dn_v = int(dn[y, x])
        expected = dn_v * SCALE + OFFSET if dn_v != 0 else NODATA
        got = float(refl[y, x])
        if dn_v == 0:
            ok = math.isnan(got)
        else:
            ok = abs(got - expected) < 1e-6
        if not ok:
            sample_ok = False
        sample_detail.append(f"({y},{x}) dn={dn_v} expected={expected} got={got}")

    # Casos explícitos requeridos: DN=1000, DN=10000, DN=11000, DN>11000.
    for target, label in [(1000, "DN=1000"), (10000, "DN=10000"), (11000, "DN=11000")]:
        locs = _find_dn_locations(dn, target)
        if locs:
            y, x = locs[0]
            got = float(refl[y, x])
            expected = target * SCALE + OFFSET
            ok = abs(got - expected) < 1e-6
            if not ok:
                sample_ok = False
            sample_detail.append(f"{label}@({y},{x}) dn={target} expected={expected} got={got}")
        else:
            sample_detail.append(f"{label}: no presente en el raster")

    # DN > 11000 (usar el máximo real).
    max_loc = int(np.argmax(dn))
    my, mx = divmod(max_loc, dn.shape[1])
    max_dn = int(dn[my, mx])
    if max_dn > 11000:
        got = float(refl[my, mx])
        expected = max_dn * SCALE + OFFSET
        ok = abs(got - expected) < 1e-6 and expected > 1.0
        if not ok:
            sample_ok = False
        sample_detail.append(f"DN>11000 max={max_dn}@({my},{mx}) expected={expected} got={got}")
    else:
        sample_detail.append(f"DN>11000: max DN={max_dn} (no supera 11000)")

    check("reflectance_numerically_coherent", sample_ok, "; ".join(sample_detail))

    check("is_cog_driver", dst_driver == "GTiff", f"driver={dst_driver}")
    check("cog_tiled", bool(dst_tiled), str(dst_blocks))
    check("cog_compression", dst_compress is not None, str(dst_compress))
    check("cog_overviews", len(dst_overviews) > 0, str(dst_overviews))
    check("cog_georeferenced", dst_transform is not None and dst_crs is not None, "")

    # Integridad y registro.
    manifest = store._load_derived_manifest(derived_id)
    fm = manifest.get("files", {}).get(relative_path)
    check("sha256_registered", bool(fm and fm.get("sha256")), str(fm.get("sha256") if fm else None))
    check("verify_derived", store.verify_derived(derived_id), "")
    check("catalog_registered", catalog.exists(derived_id), derived_id)

    return checks
