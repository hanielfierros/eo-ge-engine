"""Indices espectrales (S-A.17): SAVI, NDMI, NDWI.

Reglas cientificas:
  - Formulas aplicadas sobre REFLECTANCIA (no sobre DN crudo).
  - Mascara: cualquier input invalido (NaN) -> indice invalido (NaN).
  - Denominador == 0 -> invalido (NaN), nunca infinito.
  - Sin clipping. Sin relleno de huecos. Sin valores artificiales.
  - Precision: float32 (consistente con los productos de reflectancia S-A.16).

Definiciones (FASE 1):
  - SAVI = ((NIR - RED) / (NIR + RED + L)) * (1 + L),  L = 0.5; NIR=B08, RED=B04.
  - NDMI = (NIR - SWIR) / (NIR + SWIR);                NIR=B08, SWIR=B11.
  - NDWI (McFeeters) = (GREEN - NIR) / (GREEN + NIR);  GREEN=B03, NIR=B08.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from app.catalog.adapter import normalized_to_item
from app.catalog.catalog import Catalog
from app.connectors.base import sha256_file
from app.storage.base import FileMetadata
from app.storage.local import LocalDataStore

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

COG_OPTIONS = {"compress": "deflate", "blocksize": 512}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _band_ratio(a: np.ndarray, b: np.ndarray, add: float = 0.0, gain: float = 1.0) -> np.ndarray:
    """(a - b) / (a + b + add) * gain, con mascara de invalidez (NaN / denom 0)."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    if a.shape != b.shape:
        raise ValueError(f"dimensiones incompatibles: {a.shape} vs {b.shape}")
    denom = a + b + add
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = (a - b) / denom * gain
    out = out.astype(np.float32)
    invalid = (denom == 0) | ~np.isfinite(denom) | ~np.isfinite(a) | ~np.isfinite(b)
    out[invalid] = np.nan
    out[~np.isfinite(out)] = np.nan  # nunca producir infinitos
    return out


def savi(nir: np.ndarray, red: np.ndarray, L: float = 0.5) -> np.ndarray:
    """SAVI = ((NIR - RED) / (NIR + RED + L)) * (1 + L)."""
    return _band_ratio(nir, red, add=L, gain=1.0 + L)


def ndmi(nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """NDMI = (NIR - SWIR) / (NIR + SWIR)."""
    return _band_ratio(nir, swir)


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDWI (McFeeters) = (GREEN - NIR) / (GREEN + NIR)."""
    return _band_ratio(green, nir)


IndexFunction = Callable[..., np.ndarray]


@dataclass(frozen=True)
class IndexDefinition:
    name: str
    variable: str
    formula: str
    parameters: dict[str, Any]
    input_bands: dict[str, str]  # rol -> banda Sentinel-2
    function: IndexFunction
    input_order: tuple[str, ...]  # roles en el orden del function


INDEX_DEFINITIONS: dict[str, IndexDefinition] = {
    "SAVI": IndexDefinition(
        name="SAVI",
        variable="savi",
        formula="((NIR - RED) / (NIR + RED + L)) * (1 + L)",
        parameters={"L": 0.5},
        input_bands={"NIR": "B08", "RED": "B04"},
        function=savi,
        input_order=("NIR", "RED"),
    ),
    "NDMI": IndexDefinition(
        name="NDMI",
        variable="ndmi",
        formula="(NIR - SWIR) / (NIR + SWIR)",
        parameters={},
        input_bands={"NIR": "B08", "SWIR": "B11"},
        function=ndmi,
        input_order=("NIR", "SWIR"),
    ),
    "NDWI": IndexDefinition(
        name="NDWI",
        variable="ndwi",
        formula="(GREEN - NIR) / (GREEN + NIR)",
        parameters={},
        input_bands={"GREEN": "B03", "NIR": "B08"},
        function=ndwi,
        input_order=("GREEN", "NIR"),
    ),
}


def write_cog(path: Path, array: np.ndarray, crs: Any, transform: Any, nodata: float = float("nan")) -> Path:
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
        "compress": COG_OPTIONS["compress"],
        "blocksize": COG_OPTIONS["blocksize"],
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype("float32"), 1)
    return path


def _build_index_metadata(
    source_meta: dict[str, Any],
    definition: IndexDefinition,
    derived_id: str,
    input_product_ids: dict[str, str],
    crs: str,
    epsg: int,
    bounds: list[float],
    transform: list[float],
    width: int,
    height: int,
    cog_sha256: str,
    processing_time: str,
    resolution: tuple[float, float] = (10.0, 10.0),
    extra_transformations: list[str] | None = None,
) -> dict[str, Any]:
    """Construye metadata de un producto indice conforme al contrato V1.0.

    La informacion del indice (nombre, formula, parametros, bandas, mascara) se
    registra en `processing.transformations` y `provenance.transformations`
    (unico canal extensible del contrato V1.0 FROZEN).
    """
    source = source_meta.get("source", {})
    acquisition = source_meta.get("acquisition", {})
    spatial = source_meta.get("spatial", {})
    provenance = source_meta.get("provenance", {})

    input_bands = ";".join(f"{role}={definition.input_bands[role]}" for role in definition.input_order)
    input_products = ",".join(input_product_ids[role] for role in definition.input_order)
    params = ";".join(f"{k}={v}" for k, v in definition.parameters.items()) or "(sin parametros)"

    transformations = [
        f"index.name={definition.name}",
        f"index.formula={definition.formula}",
        f"index.parameters={params}",
        f"index.input_bands={input_bands}",
        f"index.input_products={input_products}",
        "index.mask_definition=entrada_invalida(NaN)->NaN; denominador==0->NaN; sin clipping; sin relleno",
    ]
    for extra in extra_transformations or []:
        transformations.append(extra)

    metadata: dict[str, Any] = {
        "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION, "schema_version": CONTRACT_VERSION},
        "identity": {"id": derived_id, "version": "v1"},
        "data_class": DATA_CLASS,
        "source": source,
        "product": {
            "product": definition.name,
            "product_type": "Spectral Index",
            "processing_level": source_meta.get("product", {}).get("processing_level"),
        },
        "acquisition": acquisition,
        "processing": {"processing_type": "DERIVED", "transformations": transformations},
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
                        "name": definition.name,
                        "variable": definition.variable,
                        "units": "1",
                        "dtype": "float32",
                        "scale": 1.0,
                        "offset": 0.0,
                        "nodata": "nan",
                    }
                ],
                "dimensions": {"x": width, "y": height, "band": 1},
            },
            "storage": {"format": "COG", "asset_id": derived_id, "checksum": cog_sha256},
        },
        "quality": {"status": "AVAILABLE"},
        "provenance": {
            "source_url": provenance.get("source_url"),
            "provider": provenance.get("provider"),
            "original_product": provenance.get("original_product"),
            "download_time": provenance.get("download_time"),
            "processing_time": processing_time,
            "processing_software": SOFTWARE,
            "processing_version": SOFTWARE_VERSION,
            "transformations": transformations,
            "checksum": cog_sha256,
            "license": provenance.get("license"),
            "parent_dataset": (source_meta.get("identity") or {}).get("id"),
        },
    }
    return metadata


@dataclass
class IndexResult:
    derived_id: str
    index_name: str
    relative_path: str
    cog_path: Path
    cog_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_id": self.derived_id,
            "index_name": self.index_name,
            "relative_path": self.relative_path,
            "cog_path": str(self.cog_path),
            "cog_sha256": self.cog_sha256,
            "checks": self.checks,
        }


def _read_input(store: LocalDataStore, product_id: str, relative_path: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Lee una banda de reflectancia (float32) y devuelve (array, meta_raster)."""
    path = store.get_derived_file(product_id, relative_path)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"input no disponible: {product_id}/{relative_path}")
    with rasterio.open(path) as ds:
        meta = {
            "crs": ds.crs,
            "epsg": ds.crs.to_epsg() if ds.crs else None,
            "transform": ds.transform,
            "width": ds.width,
            "height": ds.height,
            "bounds": [float(ds.bounds.left), float(ds.bounds.bottom), float(ds.bounds.right), float(ds.bounds.top)],
        }
        arr = ds.read(1)
    return arr, meta


def derive_index_product(
    store: LocalDataStore,
    catalog: Catalog,
    definition: IndexDefinition,
    input_products: dict[str, tuple[str, str]],  # role -> (derived_id, relative_path)
    derived_id: str,
) -> IndexResult:
    """Deriva un indice espectral (COG) a partir de bandas de reflectancia COG.

    Verifica alineacion geometrica entre inputs antes de calcular; sin reproyeccion.
    """
    arrays: dict[str, np.ndarray] = {}
    metas: dict[str, dict[str, Any]] = {}
    for role in definition.input_order:
        if role not in input_products:
            raise ValueError(f"input faltante para rol {role!r}")
        pid, rel = input_products[role]
        arr, meta = _read_input(store, pid, rel)
        arrays[role] = arr
        metas[role] = meta

    # Validacion geometrica: todos los inputs deben coincidir.
    ref = metas[definition.input_order[0]]
    for role in definition.input_order[1:]:
        m = metas[role]
        if m["crs"].to_epsg() != ref["crs"].to_epsg() or m["transform"] != ref["transform"] or (m["width"], m["height"]) != (ref["width"], ref["height"]):
            raise ValueError(f"inputs geometricamente incompatibles: {role} vs {definition.input_order[0]}")

    # Calcular indice.
    args = [arrays[role] for role in definition.input_order]
    index_arr = definition.function(*args)

    rel = f"{definition.name}_10m.tif"
    source_meta = store.get_derived_metadata(input_products[definition.input_order[0]][0])
    if source_meta is None:
        raise RuntimeError("metadata de input no encontrada")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cog = Path(tmpdir) / rel
        write_cog(tmp_cog, index_arr, ref["crs"], ref["transform"])
        cog_sha = sha256_file(tmp_cog)

        if store.exists_derived(derived_id):
            existing = store.get_derived_file(derived_id, rel)
            if existing is not None and existing.is_file() and sha256_file(existing) == cog_sha:
                return IndexResult(
                    derived_id=derived_id, index_name=definition.name, relative_path=rel,
                    cog_path=existing, cog_sha256=cog_sha,
                    metadata=store.get_derived_metadata(derived_id) or {},
                )
            raise RuntimeError(f"producto derivado ya existe con contenido distinto: {derived_id}")

        gdal_transform = list(ref["transform"].to_gdal())
        metadata = _build_index_metadata(
            source_meta=source_meta,
            definition=definition,
            derived_id=derived_id,
            input_product_ids={role: input_products[role][0] for role in definition.input_order},
            crs=f"EPSG:{ref['epsg']}" if ref["epsg"] else str(ref["crs"]),
            epsg=ref["epsg"],
            bounds=ref["bounds"],
            transform=gdal_transform,
            width=ref["width"],
            height=ref["height"],
            cog_sha256=cog_sha,
            processing_time=_utc_iso(),
        )

        store.put_derived_metadata(derived_id, metadata)
        file_meta = FileMetadata(
            filename=rel, relative_path=rel,
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            role="data", format="COG", source_generated="generated",
        )
        store.put_derived_file(derived_id, file_meta, tmp_cog)

        catalog.register_collection(COLLECTION)
        storage_path = f"derived/{derived_id}"
        asset_record = {
            "asset_key": definition.name,
            "href": f"{storage_path}/files/{rel}",
            "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "role": "data", "title": rel, "size": file_meta.size,
            "checksum": cog_sha, "format": "COG",
        }
        item = normalized_to_item(metadata, storage_path=storage_path, materialized_files={definition.name: asset_record})
        if not catalog.exists(derived_id):
            catalog.register_item(item)
        else:
            catalog.register_asset(derived_id, asset_record)

        final_cog = store.get_derived_file(derived_id, rel)
        if final_cog is None or sha256_file(final_cog) != cog_sha:
            raise RuntimeError("producto derivado no recuperable tras persistir")

    return IndexResult(
        derived_id=derived_id, index_name=definition.name, relative_path=rel,
        cog_path=final_cog, cog_sha256=cog_sha, metadata=metadata,
    )


def validate_index_product(
    store: LocalDataStore,
    catalog: Catalog,
    derived_id: str,
    relative_path: str,
    input_products: dict[str, tuple[str, str]],
    definition: IndexDefinition,
    expected_crs_epsg: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Valida un producto indice y devuelve (checks, estadisticas)."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    cog_path = store.get_derived_file(derived_id, relative_path)
    check("file_exists", cog_path is not None and cog_path.is_file(), str(cog_path))
    if cog_path is None or not cog_path.is_file():
        return checks, {}

    arrays = {}
    metas = {}
    for role in definition.input_order:
        pid, rel = input_products[role]
        arr, meta = _read_input(store, pid, rel)
        arrays[role] = arr
        metas[role] = meta
    ref = metas[definition.input_order[0]]

    with rasterio.open(cog_path) as dst:
        dst_driver = dst.driver
        dst_crs = dst.crs
        dst_transform = dst.transform
        dst_width, dst_height = dst.width, dst.height
        dst_nodata = dst.nodata
        dst_blocks = dst.block_shapes[0]
        dst_overviews = dst.overviews(1)
        dst_compress = dst.compression
        dst_tiled = dst_blocks[0] < dst_width or dst_blocks[1] < dst_height
        idx = dst.read(1)

    check("opens_with_rasterio", True, f"driver={dst_driver}")
    check("crs_correct", dst_crs is not None and dst_crs.to_epsg() == expected_crs_epsg, str(dst_crs))
    check("transform_correct", dst_transform == ref["transform"], str(dst_transform))
    check("dimensions_correct", dst_width == ref["width"] and dst_height == ref["height"], f"{dst_width}x{dst_height}")
    check("aligned_with_inputs", dst_transform == ref["transform"], "")
    check("dtype_float32", dst.dtypes[0] == "float32", dst.dtypes[0])
    check("nodata_is_nan", dst_nodata is not None and np.isnan(float(dst_nodata)), str(dst_nodata))

    # Recomponer el indice desde los inputs para verificacion numerica independiente.
    args = [arrays[role] for role in definition.input_order]
    expected = definition.function(*args)

    nan_mask = np.isnan(idx)
    n_invalid = int(np.count_nonzero(np.isnan(expected)))
    n_nan = int(np.count_nonzero(nan_mask))
    check("mask_coherent", n_nan == n_invalid, f"expected_invalid={n_invalid} cog_nan={n_nan}")
    check("no_inf", int(np.count_nonzero(np.isinf(idx))) == 0, "")
    check("dn0_reflectance_invalid", bool(np.all(nan_mask == np.isnan(expected))), "")

    # Muestra determinista (indices validos).
    h, w = idx.shape
    pts = [(0, 0), (0, 1), (1, 0), (h - 1, w - 1), (h // 2, w // 2)]
    ok_sample = True
    for y, x in pts:
        a = float(arrays[definition.input_order[0]][y, x])
        b = float(arrays[definition.input_order[1]][y, x])
        exp = float(expected[y, x])
        got = float(idx[y, x])
        if np.isnan(exp):
            ok_sample = ok_sample and np.isnan(got)
        else:
            ok_sample = ok_sample and abs(got - exp) < 1e-6
    check("numerically_coherent", ok_sample, "")

    # Estadisticas (sobre valores validos).
    valid = idx[np.isfinite(idx)]
    stats = {
        "total_pixels": int(idx.size),
        "valid_pixels": int(np.count_nonzero(np.isfinite(idx))),
        "invalid_pixels": int(np.count_nonzero(~np.isfinite(idx))),
        "pct_valid": float(np.count_nonzero(np.isfinite(idx))) / idx.size * 100.0,
        "pct_invalid": float(np.count_nonzero(~np.isfinite(idx))) / idx.size * 100.0,
        "nan_count": int(np.count_nonzero(np.isnan(idx))),
        "inf_count": int(np.count_nonzero(np.isinf(idx))),
    }
    if valid.size > 0:
        stats["min"] = float(np.min(valid))
        stats["max"] = float(np.max(valid))
        stats["mean"] = float(np.mean(valid))
        stats["p01"] = float(np.percentile(valid, 1))
        stats["p50"] = float(np.percentile(valid, 50))
        stats["p99"] = float(np.percentile(valid, 99))
    stats["out_of_expected_range"] = None
    if valid.size > 0 and definition.name in ("NDMI", "NDWI", "SAVI"):
        lo, hi = (-1.0, 1.0)
        stats["count_below_minus1"] = int(np.count_nonzero(valid < lo))
        stats["count_above_1"] = int(np.count_nonzero(valid > hi))

    check("is_cog_driver", dst_driver == "GTiff", f"driver={dst_driver}")
    check("cog_tiled", bool(dst_tiled), str(dst_blocks))
    check("cog_compression", dst_compress is not None, str(dst_compress))
    check("cog_overviews", len(dst_overviews) > 0, str(dst_overviews))
    check("sha256_registered", store.verify_derived(derived_id), "")
    check("catalog_registered", catalog.exists(derived_id), derived_id)

    return checks, stats


def _resample_to_grid(
    src: np.ndarray,
    src_transform: Any,
    src_crs: Any,
    dst_transform: Any,
    dst_crs: Any,
    dst_width: int,
    dst_height: int,
    resampling: str = "bilinear",
) -> np.ndarray:
    """Reamuestra/reproyecta una banda float32 a un grid destino explicito.

    Uso exclusivo del metodo bilinear para reflectancia continua; sin interpolacion
    oculta. nodata de entrada y salida = NaN.
    """
    try:
        resampling_enum = Resampling.bilinear if resampling == "bilinear" else Resampling[resampling]
    except KeyError as exc:
        raise ValueError(f"resampling no soportado: {resampling!r}") from exc
    dst = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
    reproject(
        source=np.asarray(src, dtype=np.float32),
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=float("nan"),
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=float("nan"),
        resampling=resampling_enum,
    )
    return dst


def derive_resampled_index(
    store: LocalDataStore,
    catalog: Catalog,
    definition: IndexDefinition,
    input_products: dict[str, tuple[str, str]],
    derived_id: str,
    target_grid_role: str,
    resampling: str = "bilinear",
) -> IndexResult:
    """Deriva un indice espectral cuyos inputs NO comparten el mismo grid.

    `target_grid_role` indica el rol cuyo grid nativo define la salida (p. ej.
    SWIR/B11 20 m para NDMI). Los demas inputs se reamuestran a ese grid con el
    `resampling` indicado. La transformacion queda registrada en provenance.
    """
    arrays: dict[str, np.ndarray] = {}
    metas: dict[str, dict[str, Any]] = {}
    for role in definition.input_order:
        if role not in input_products:
            raise ValueError(f"input faltante para rol {role!r}")
        pid, rel = input_products[role]
        arr, meta = _read_input(store, pid, rel)
        arrays[role] = arr
        metas[role] = meta

    if target_grid_role not in metas:
        raise ValueError(f"target_grid_role {target_grid_role!r} no esta entre los inputs")

    target = metas[target_grid_role]
    processed: dict[str, np.ndarray] = {}
    resampled_roles: list[str] = []
    for role in definition.input_order:
        m = metas[role]
        same_grid = (
            role == target_grid_role
            or (
                m["crs"].to_epsg() == target["crs"].to_epsg()
                and m["transform"] == target["transform"]
                and (m["width"], m["height"]) == (target["width"], target["height"])
            )
        )
        if same_grid:
            processed[role] = arrays[role]
        else:
            processed[role] = _resample_to_grid(
                arrays[role], m["transform"], m["crs"],
                target["transform"], target["crs"],
                target["width"], target["height"], resampling=resampling,
            )
            resampled_roles.append(role)

    args = [processed[role] for role in definition.input_order]
    index_arr = definition.function(*args)

    res_x = float(abs(target["transform"].a))
    res_y = float(abs(target["transform"].e))
    res_m = int(round(res_x))
    rel = f"{definition.name}_{res_m}m.tif"

    source_meta = store.get_derived_metadata(input_products[definition.input_order[0]][0])
    if source_meta is None:
        raise RuntimeError("metadata de input no encontrada")

    extra_transformations: list[str] = []
    for role in resampled_roles:
        src_res = int(round(abs(metas[role]["transform"].a)))
        extra_transformations.append(
            f"resampling.role={role};source={definition.input_bands[role]} {src_res}m;"
            f"target_grid={target_grid_role} {res_m}m;method={resampling};"
            f"source_nodata=nan;dest_nodata=nan"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cog = Path(tmpdir) / rel
        write_cog(tmp_cog, index_arr, target["crs"], target["transform"])
        cog_sha = sha256_file(tmp_cog)

        if store.exists_derived(derived_id):
            existing = store.get_derived_file(derived_id, rel)
            if existing is not None and existing.is_file() and sha256_file(existing) == cog_sha:
                return IndexResult(
                    derived_id=derived_id, index_name=definition.name, relative_path=rel,
                    cog_path=existing, cog_sha256=cog_sha,
                    metadata=store.get_derived_metadata(derived_id) or {},
                )
            raise RuntimeError(f"producto derivado ya existe con contenido distinto: {derived_id}")

        gdal_transform = list(target["transform"].to_gdal())
        metadata = _build_index_metadata(
            source_meta=source_meta,
            definition=definition,
            derived_id=derived_id,
            input_product_ids={role: input_products[role][0] for role in definition.input_order},
            crs=f"EPSG:{target['epsg']}" if target["epsg"] else str(target["crs"]),
            epsg=target["epsg"],
            bounds=target["bounds"],
            transform=gdal_transform,
            width=target["width"],
            height=target["height"],
            cog_sha256=cog_sha,
            processing_time=_utc_iso(),
            resolution=(res_x, res_y),
            extra_transformations=extra_transformations,
        )

        store.put_derived_metadata(derived_id, metadata)
        file_meta = FileMetadata(
            filename=rel, relative_path=rel,
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            role="data", format="COG", source_generated="generated",
        )
        store.put_derived_file(derived_id, file_meta, tmp_cog)

        catalog.register_collection(COLLECTION)
        storage_path = f"derived/{derived_id}"
        asset_record = {
            "asset_key": definition.name,
            "href": f"{storage_path}/files/{rel}",
            "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "role": "data", "title": rel, "size": file_meta.size,
            "checksum": cog_sha, "format": "COG",
        }
        item = normalized_to_item(metadata, storage_path=storage_path, materialized_files={definition.name: asset_record})
        if not catalog.exists(derived_id):
            catalog.register_item(item)
        else:
            catalog.register_asset(derived_id, asset_record)

        final_cog = store.get_derived_file(derived_id, rel)
        if final_cog is None or sha256_file(final_cog) != cog_sha:
            raise RuntimeError("producto derivado no recuperable tras persistir")

    return IndexResult(
        derived_id=derived_id, index_name=definition.name, relative_path=rel,
        cog_path=final_cog, cog_sha256=cog_sha, metadata=metadata,
    )


def validate_resampled_index_product(
    store: LocalDataStore,
    catalog: Catalog,
    derived_id: str,
    relative_path: str,
    input_products: dict[str, tuple[str, str]],
    definition: IndexDefinition,
    target_grid_role: str,
    expected_crs_epsg: int,
    expected_width: int,
    expected_height: int,
    expected_res: tuple[float, float],
    resampling: str = "bilinear",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Valida un indice reamuestrado (p. ej. NDMI 20 m) y devuelve (checks, stats)."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    cog_path = store.get_derived_file(derived_id, relative_path)
    check("file_exists", cog_path is not None and cog_path.is_file(), str(cog_path))
    if cog_path is None or not cog_path.is_file():
        return checks, {}

    arrays: dict[str, np.ndarray] = {}
    metas: dict[str, dict[str, Any]] = {}
    for role in definition.input_order:
        pid, rel = input_products[role]
        arr, meta = _read_input(store, pid, rel)
        arrays[role] = arr
        metas[role] = meta
    target = metas[target_grid_role]

    processed: dict[str, np.ndarray] = {}
    for role in definition.input_order:
        m = metas[role]
        same_grid = (
            role == target_grid_role
            or (m["crs"].to_epsg() == target["crs"].to_epsg()
                and m["transform"] == target["transform"]
                and (m["width"], m["height"]) == (target["width"], target["height"]))
        )
        if same_grid:
            processed[role] = arrays[role]
        else:
            processed[role] = _resample_to_grid(
                arrays[role], m["transform"], m["crs"],
                target["transform"], target["crs"],
                target["width"], target["height"], resampling=resampling,
            )

    args = [processed[role] for role in definition.input_order]
    expected = definition.function(*args)

    with rasterio.open(cog_path) as dst:
        dst_driver = dst.driver
        dst_crs = dst.crs
        dst_transform = dst.transform
        dst_width, dst_height = dst.width, dst.height
        dst_nodata = dst.nodata
        dst_blocks = dst.block_shapes[0]
        dst_overviews = dst.overviews(1)
        dst_compress = dst.compression
        dst_tiled = dst_blocks[0] < dst_width or dst_blocks[1] < dst_height
        dst_res = dst.res
        idx = dst.read(1)

    check("opens_with_rasterio", True, f"driver={dst_driver}")
    check("crs_correct", dst_crs is not None and dst_crs.to_epsg() == expected_crs_epsg, str(dst_crs))
    check("transform_correct", dst_transform == target["transform"], str(dst_transform))
    check("dimensions_correct", dst_width == expected_width and dst_height == expected_height, f"{dst_width}x{dst_height}")
    check("resolution_correct", abs(dst_res[0] - expected_res[0]) < 1e-9 and abs(dst_res[1] - expected_res[1]) < 1e-9, str(dst_res))
    check("dtype_float32", dst.dtypes[0] == "float32", dst.dtypes[0])
    check("nodata_is_nan", dst_nodata is not None and np.isnan(float(dst_nodata)), str(dst_nodata))

    # Mascara: NaN del indice debe coincidir con el NaN de la recomposicion independiente.
    nan_mask = np.isnan(idx)
    exp_nan = np.isnan(expected)
    check("mask_coherent", int(np.count_nonzero(nan_mask)) == int(np.count_nonzero(exp_nan)), "")
    check("no_inf", int(np.count_nonzero(np.isinf(idx))) == 0, "")

    # Comparacion numerica (tolerancia float32) sobre pixeles validos.
    finite = np.isfinite(expected)
    if int(np.count_nonzero(finite)) > 0:
        diff = np.abs(idx[finite] - expected[finite])
        max_diff = float(np.max(diff))
        ok_num = bool(np.allclose(idx[finite], expected[finite], atol=1e-5, rtol=1e-5, equal_nan=True))
    else:
        max_diff = 0.0
        ok_num = True
    check("numerically_coherent", ok_num, f"max_abs_diff={max_diff}")

    # Denom == 0 y no finitos -> NaN (nunca infinito).
    denom_zero_or_invalid = (~np.isfinite(processed[definition.input_order[0]] + processed[definition.input_order[1]])) | ((processed[definition.input_order[0]] + processed[definition.input_order[1]]) == 0)
    check("denom_zero_is_nan", bool(np.all(np.isnan(idx[denom_zero_or_invalid]))), "")

    # Estadisticas sobre valores validos.
    valid = idx[np.isfinite(idx)]
    stats: dict[str, Any] = {
        "total_pixels": int(idx.size),
        "valid_pixels": int(np.count_nonzero(np.isfinite(idx))),
        "invalid_pixels": int(np.count_nonzero(~np.isfinite(idx))),
        "pct_valid": float(np.count_nonzero(np.isfinite(idx))) / idx.size * 100.0,
        "pct_invalid": float(np.count_nonzero(~np.isfinite(idx))) / idx.size * 100.0,
        "nan_count": int(np.count_nonzero(np.isnan(idx))),
        "inf_count": int(np.count_nonzero(np.isinf(idx))),
    }
    if valid.size > 0:
        stats["min"] = float(np.min(valid))
        stats["max"] = float(np.max(valid))
        stats["mean"] = float(np.mean(valid))
        stats["p01"] = float(np.percentile(valid, 1))
        stats["p50"] = float(np.percentile(valid, 50))
        stats["p99"] = float(np.percentile(valid, 99))
        stats["count_below_minus1"] = int(np.count_nonzero(valid < -1.0))
        stats["count_above_1"] = int(np.count_nonzero(valid > 1.0))

    check("is_cog_driver", dst_driver == "GTiff", f"driver={dst_driver}")
    check("cog_tiled", bool(dst_tiled), str(dst_blocks))
    check("cog_compression", dst_compress is not None, str(dst_compress))
    check("cog_overviews", len(dst_overviews) > 0, str(dst_overviews))
    check("sha256_registered", store.verify_derived(derived_id), "")
    check("catalog_registered", catalog.exists(derived_id), derived_id)

    return checks, stats
