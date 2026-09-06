"""Tests de indices espectrales (S-A.17): SAVI, NDMI, NDWI.

Cubren: formulas (con expected independiente), denominador cero, NaN, mascara,
dimensiones incompatibles, precisión float32, idempotencia, path safety y
metadata/contrato. Usan datos sinteticos (sin datos Sentinel-2 reales).

    python -m unittest tests.test_spectral_indices -v
"""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio

from app.catalog.catalog import Catalog
from app.connectors.base import SourceRepresentation, sha256_file
from app.normalizers.base import validate_against_contract
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.processing.indices import (
    INDEX_DEFINITIONS,
    derive_index_product,
    derive_resampled_index,
    ndmi,
    ndwi,
    savi,
    validate_index_product,
    validate_resampled_index_product,
)
from app.storage.base import FileMetadata, StorageError
from app.storage.local import LocalDataStore

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"


def _source_metadata() -> dict:
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sr = SourceRepresentation(
        source=d["source"], product=d["product"], source_id=d["source_id"],
        source_metadata=d["source_metadata"], acquisition=d["acquisition"],
        spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
        checksum=d["checksum"], provenance=d["provenance"],
        collection_metadata=d["collection_metadata"],
    )
    return Sentinel2L2ANormalizer().normalize(sr)


def _write_ref_cog(store: LocalDataStore, derived_id: str, rel: str, arr: np.ndarray, crs, transform) -> None:
    from app.processing.raster import _build_derived_metadata  # reutiliza metadata de reflectancia

    meta = _source_metadata()
    import tempfile as _tf

    with _tf.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / rel
        from app.processing.indices import write_cog

        write_cog(p, arr, crs, transform)
        import rasterio as _r

        with _r.open(p) as ds:
            bounds = [float(ds.bounds.left), float(ds.bounds.bottom), float(ds.bounds.right), float(ds.bounds.top)]
            gdal_transform = list(ds.transform.to_gdal())
            width, height = ds.width, ds.height
            epsg = ds.crs.to_epsg()
        m = _build_derived_metadata(
            source_meta=meta, derived_id=derived_id, band_name="BXX", band_variable="x",
            crs=f"EPSG:{epsg}", epsg=epsg, bounds=bounds, transform=gdal_transform,
            width=width, height=height, cog_sha256=sha256_file(p), processing_time="2026-09-06T00:00:00Z",
        )
        store.put_derived_metadata(derived_id, m)
        store.put_derived_file(derived_id, FileMetadata(filename=rel, relative_path=rel, media_type="image/tiff", role="data", format="COG"), p)


class TestFormula(unittest.TestCase):
    def test_savi_normal(self):
        got = savi(np.array([0.5], dtype=np.float32), np.array([0.2], dtype=np.float32))
        self.assertAlmostEqual(float(got[0]), 0.375, places=6)  # (0.3/1.2)*1.5

    def test_savi_identity_high(self):
        # nir==red -> 0
        got = savi(np.array([0.3], dtype=np.float32), np.array([0.3], dtype=np.float32))
        self.assertAlmostEqual(float(got[0]), 0.0, places=6)

    def test_savi_denominator_problematic(self):
        # nir+red+L == 0 -> NaN
        got = savi(np.array([-0.25], dtype=np.float32), np.array([-0.25], dtype=np.float32))
        self.assertTrue(math.isnan(float(got[0])))  # -0.25 + -0.25 + 0.5 = 0

    def test_savi_nan_propagates(self):
        got = savi(np.array([np.nan], dtype=np.float32), np.array([0.2], dtype=np.float32))
        self.assertTrue(math.isnan(float(got[0])))

    def test_ndmi_normal(self):
        got = ndmi(np.array([0.5], dtype=np.float32), np.array([0.3], dtype=np.float32))
        self.assertAlmostEqual(float(got[0]), 0.25, places=6)  # 0.2/0.8

    def test_ndmi_denominator_zero(self):
        got = ndmi(np.array([0.5], dtype=np.float32), np.array([-0.5], dtype=np.float32))
        self.assertTrue(math.isnan(float(got[0])))

    def test_ndwi_normal(self):
        got = ndwi(np.array([0.4], dtype=np.float32), np.array([0.1], dtype=np.float32))
        self.assertAlmostEqual(float(got[0]), 0.6, places=6)  # 0.3/0.5

    def test_ndwi_denominator_zero(self):
        got = ndwi(np.array([0.2], dtype=np.float32), np.array([-0.2], dtype=np.float32))
        self.assertTrue(math.isnan(float(got[0])))

    def test_no_inf_ever(self):
        a = np.array([1e38, np.nan, 0.0, -1e38], dtype=np.float32)
        b = np.array([-1e38, 0.0, 0.0, 1e38], dtype=np.float32)
        for fn in (savi, ndmi, ndwi):
            out = fn(a, b)
            self.assertEqual(int(np.count_nonzero(np.isinf(out))), 0)

    def test_shape_mismatch(self):
        with self.assertRaises(ValueError):
            ndmi(np.zeros((4, 4), dtype=np.float32), np.zeros((4, 5), dtype=np.float32))

    def test_float32_output(self):
        out = savi(np.array([0.5], dtype=np.float32), np.array([0.2], dtype=np.float32))
        self.assertEqual(out.dtype, np.float32)

    def test_mask_partial(self):
        nir = np.array([[0.5, 0.3], [np.nan, 0.4]], dtype=np.float32)
        red = np.array([[0.2, 0.3], [0.2, np.nan]], dtype=np.float32)
        out = savi(nir, red)
        self.assertFalse(math.isnan(float(out[0, 0])))
        self.assertTrue(math.isnan(float(out[1, 0])))
        self.assertTrue(math.isnan(float(out[1, 1])))


class TestIndexDerive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = LocalDataStore(self.root)
        self.catalog = Catalog(self.root / "catalog.sqlite")
        self.crs = rasterio.crs.CRS.from_epsg(32612)
        self.transform = rasterio.transform.from_origin(699960.0, 2900040.0, 10, 10)
        # bandas sinteticas 512x512 con valores de reflectancia
        rng = np.random.default_rng(7)
        self.red = (rng.random((2048, 2048)) * 0.3).astype(np.float32)
        self.nir = (rng.random((2048, 2048)) * 0.5 + 0.1).astype(np.float32)
        self.red[0, 0] = np.nan
        self.nir[1, 1] = np.nan
        self.red_id = "S2_B04_REFL_v1"
        self.nir_id = "S2_B08_REFL_v1"
        _write_ref_cog(self.store, self.red_id, "B04_10m_reflectance.tif", self.red, self.crs, self.transform)
        _write_ref_cog(self.store, self.nir_id, "B08_10m_reflectance.tif", self.nir, self.crs, self.transform)

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def test_derive_savi(self):
        did = "S2_SAVI_v1"
        res = derive_index_product(
            self.store, self.catalog, INDEX_DEFINITIONS["SAVI"],
            {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "RED": (self.red_id, "B04_10m_reflectance.tif")},
            did,
        )
        self.assertTrue(self.store.verify_derived(did))
        self.assertTrue(self.catalog.exists(did))
        checks, stats = validate_index_product(
            self.store, self.catalog, did, res.relative_path,
            {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "RED": (self.red_id, "B04_10m_reflectance.tif")},
            INDEX_DEFINITIONS["SAVI"], 32612,
        )
        failures = [c for c in checks if c["result"] != "PASS"]
        self.assertEqual(failures, [], f"FAIL: {failures}")

    def test_derive_idempotent(self):
        did = "S2_SAVI_v1"
        a = derive_index_product(self.store, self.catalog, INDEX_DEFINITIONS["SAVI"],
                                 {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "RED": (self.red_id, "B04_10m_reflectance.tif")}, did)
        b = derive_index_product(self.store, self.catalog, INDEX_DEFINITIONS["SAVI"],
                                 {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "RED": (self.red_id, "B04_10m_reflectance.tif")}, did)
        self.assertEqual(a.cog_sha256, b.cog_sha256)
        self.assertTrue(self.store.verify_derived(did))

    def test_metadata_contract_valid(self):
        did = "S2_SAVI_v1"
        derive_index_product(self.store, self.catalog, INDEX_DEFINITIONS["SAVI"],
                             {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "RED": (self.red_id, "B04_10m_reflectance.tif")}, did)
        meta = self.store.get_derived_metadata(did)
        self.assertEqual(validate_against_contract(meta), [])
        self.assertEqual(meta["data_class"], "DERIVED_PRODUCT")
        tr = meta["processing"]["transformations"]
        self.assertTrue(any(t.startswith("index.name=SAVI") for t in tr))
        self.assertTrue(any("L=0.5" in t for t in tr))

    def test_missing_input(self):
        with self.assertRaises(ValueError):
            derive_index_product(self.store, self.catalog, INDEX_DEFINITIONS["SAVI"],
                                 {"NIR": (self.nir_id, "B08_10m_reflectance.tif")}, "S2_SAVI_v2")

    def test_geometric_mismatch(self):
        # input RED con transform distinto -> debe fallar
        other_transform = rasterio.transform.from_origin(600000.0, 2900000.0, 10, 10)
        _write_ref_cog(self.store, "S2_B04_OFFSET_v1", "B04_10m_reflectance.tif", self.red, self.crs, other_transform)
        with self.assertRaises(ValueError):
            derive_index_product(self.store, self.catalog, INDEX_DEFINITIONS["SAVI"],
                                 {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "RED": ("S2_B04_OFFSET_v1", "B04_10m_reflectance.tif")}, "S2_SAVI_v3")

    def test_no_secrets_in_metadata(self):
        did = "S2_SAVI_v1"
        derive_index_product(self.store, self.catalog, INDEX_DEFINITIONS["SAVI"],
                             {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "RED": (self.red_id, "B04_10m_reflectance.tif")}, did)
        blob = json.dumps(self.store.get_derived_metadata(did)).lower()
        for s in ("token", "password", "secret", "bearer", "client_secret"):
            self.assertNotIn(s, blob)


class TestNDWIDerive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = LocalDataStore(self.root)
        self.catalog = Catalog(self.root / "catalog.sqlite")
        self.crs = rasterio.crs.CRS.from_epsg(32612)
        self.transform = rasterio.transform.from_origin(699960.0, 2900040.0, 10, 10)
        rng = np.random.default_rng(11)
        self.green = (rng.random((2048, 2048)) * 0.3 + 0.05).astype(np.float32)
        self.nir = (rng.random((2048, 2048)) * 0.5 + 0.1).astype(np.float32)
        self.green[0, 0] = np.nan
        self.nir[1, 1] = np.nan
        self.green_id = "S2_B03_REFL_v1"
        self.nir_id = "S2_B08_REFL_v1"
        _write_ref_cog(self.store, self.green_id, "B03_10m.tif", self.green, self.crs, self.transform)
        _write_ref_cog(self.store, self.nir_id, "B08_10m_reflectance.tif", self.nir, self.crs, self.transform)

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def test_derive_ndwi(self):
        did = "S2_NDWI_v1"
        res = derive_index_product(
            self.store, self.catalog, INDEX_DEFINITIONS["NDWI"],
            {"GREEN": (self.green_id, "B03_10m.tif"), "NIR": (self.nir_id, "B08_10m_reflectance.tif")},
            did,
        )
        self.assertEqual(res.relative_path, "NDWI_10m.tif")
        self.assertTrue(self.store.verify_derived(did))
        self.assertTrue(self.catalog.exists(did))
        checks, stats = validate_index_product(
            self.store, self.catalog, did, res.relative_path,
            {"GREEN": (self.green_id, "B03_10m.tif"), "NIR": (self.nir_id, "B08_10m_reflectance.tif")},
            INDEX_DEFINITIONS["NDWI"], 32612,
        )
        failures = [c for c in checks if c["result"] != "PASS"]
        self.assertEqual(failures, [], f"FAIL: {failures}")


class TestNDMIResampled(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = LocalDataStore(self.root)
        self.catalog = Catalog(self.root / "catalog.sqlite")
        self.crs = rasterio.crs.CRS.from_epsg(32612)
        self.t10 = rasterio.transform.from_origin(699960.0, 2900040.0, 10, 10)
        self.t20 = rasterio.transform.from_origin(699960.0, 2900040.0, 20, 20)
        rng = np.random.default_rng(13)
        self.nir10 = (rng.random((2048, 2048)) * 0.5 + 0.1).astype(np.float32)
        self.swir20 = (rng.random((1024, 1024)) * 0.4 + 0.05).astype(np.float32)
        self.nir10[0, 0] = np.nan
        self.swir20[1, 1] = np.nan
        self.nir_id = "S2_B08_REFL_v1"
        self.swir_id = "S2_B11_REFL_v1"
        _write_ref_cog(self.store, self.nir_id, "B08_10m_reflectance.tif", self.nir10, self.crs, self.t10)
        _write_ref_cog(self.store, self.swir_id, "B11_20m.tif", self.swir20, self.crs, self.t20)

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def test_derive_ndmi_20m(self):
        did = "S2_NDMI_v1"
        res = derive_resampled_index(
            self.store, self.catalog, INDEX_DEFINITIONS["NDMI"],
            {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "SWIR": (self.swir_id, "B11_20m.tif")},
            did, target_grid_role="SWIR", resampling="bilinear",
        )
        self.assertEqual(res.relative_path, "NDMI_20m.tif")
        self.assertTrue(self.store.verify_derived(did))
        self.assertTrue(self.catalog.exists(did))
        with rasterio.open(res.cog_path) as ds:
            self.assertEqual(ds.width, 1024)
            self.assertEqual(ds.height, 1024)
            self.assertEqual(ds.transform, self.t20)
            self.assertAlmostEqual(ds.res[0], 20.0, places=6)
        meta = self.store.get_derived_metadata(did)
        tr = meta["processing"]["transformations"]
        self.assertTrue(any("resampling.role=NIR" in t and "method=bilinear" in t for t in tr))

    def test_validate_ndmi(self):
        did = "S2_NDMI_v1"
        res = derive_resampled_index(
            self.store, self.catalog, INDEX_DEFINITIONS["NDMI"],
            {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "SWIR": (self.swir_id, "B11_20m.tif")},
            did, target_grid_role="SWIR", resampling="bilinear",
        )
        checks, stats = validate_resampled_index_product(
            self.store, self.catalog, did, res.relative_path,
            {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "SWIR": (self.swir_id, "B11_20m.tif")},
            INDEX_DEFINITIONS["NDMI"], "SWIR", 32612, 1024, 1024, (20.0, 20.0), "bilinear",
        )
        failures = [c for c in checks if c["result"] != "PASS"]
        self.assertEqual(failures, [], f"FAIL: {failures}")

    def test_ndmi_idempotent(self):
        did = "S2_NDMI_v1"
        inputs = {"NIR": (self.nir_id, "B08_10m_reflectance.tif"), "SWIR": (self.swir_id, "B11_20m.tif")}
        a = derive_resampled_index(self.store, self.catalog, INDEX_DEFINITIONS["NDMI"], inputs, did, target_grid_role="SWIR", resampling="bilinear")
        b = derive_resampled_index(self.store, self.catalog, INDEX_DEFINITIONS["NDMI"], inputs, did, target_grid_role="SWIR", resampling="bilinear")
        self.assertEqual(a.cog_sha256, b.cog_sha256)
        self.assertTrue(self.store.verify_derived(did))

    def test_ndmi_denominator_zero_nan(self):
        _write_ref_cog(self.store, "S2_B08_ZERO_v1", "B08_10m_reflectance.tif", np.zeros((128, 128), dtype=np.float32), self.crs, self.t10)
        _write_ref_cog(self.store, "S2_B11_ZERO_v1", "B11_20m.tif", np.zeros((64, 64), dtype=np.float32), self.crs, self.t20)
        res = derive_resampled_index(
            self.store, self.catalog, INDEX_DEFINITIONS["NDMI"],
            {"NIR": ("S2_B08_ZERO_v1", "B08_10m_reflectance.tif"), "SWIR": ("S2_B11_ZERO_v1", "B11_20m.tif")},
            "S2_NDMI_ZERO_v1", target_grid_role="SWIR", resampling="bilinear",
        )
        with rasterio.open(res.cog_path) as ds:
            arr = ds.read(1)
        self.assertEqual(int(np.count_nonzero(np.isinf(arr))), 0)
        self.assertEqual(int(np.count_nonzero(np.isnan(arr))), arr.size)


if __name__ == "__main__":
    unittest.main()
