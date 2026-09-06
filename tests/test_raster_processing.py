"""Tests del procesamiento raster cientifico (S-A.16).

Cubren: formula scale/offset, DN=0, DN>10000, mascara, COG real, metadata,
checksum, idempotencia, recuperacion ante fallo, ausencia de modificacion de
fuente, ausencia de secretos y path safety. Usan datos sinteticos (sin JP2 real).

    python -m unittest tests.test_raster_processing -v
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio

from app.catalog.catalog import Catalog
from app.connectors.base import SourceRepresentation, sha256_file
from app.normalizers.base import validate_against_contract
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.processing.raster import (
    NODATA,
    OFFSET,
    SCALE,
    apply_mask,
    build_valid_mask,
    derive_band_reflectance,
    reflectance_from_dn,
    validate_derived_product,
    write_cog,
)
from app.storage.base import FileMetadata, StorageError, StorageNotFoundError
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


def _synthetic_dn(width: int = 512, height: int = 512) -> np.ndarray:
    rng = np.random.default_rng(42)
    dn = rng.integers(1, 2000, size=(height, width), dtype=np.uint16)
    dn[0, 0] = 0
    dn[0, 1] = 1000
    dn[0, 2] = 10000
    dn[0, 3] = 11000
    dn[0, 4] = 17455
    dn[1, 1] = 0
    return dn


class TestFormula(unittest.TestCase):
    def test_scale_offset_formula(self):
        dn = np.array([0, 1000, 10000, 11000, 17455], dtype=np.uint16)
        got = reflectance_from_dn(dn)
        expected = np.array([-0.1, 0.0, 0.9, 1.0, 1.6455], dtype=np.float32)
        self.assertTrue(np.allclose(got, expected, atol=1e-6))

    def test_dn0_masked_to_nan(self):
        dn = np.array([0, 1000, 5000], dtype=np.uint16)
        mask = build_valid_mask(dn)
        self.assertFalse(mask[0])
        self.assertTrue(mask[1])
        refl = apply_mask(reflectance_from_dn(dn), mask)
        self.assertTrue(math.isnan(float(refl[0])))
        self.assertAlmostEqual(float(refl[1]), 0.0, places=6)

    def test_dn_gt_10000_not_clipped(self):
        dn = np.array([11000, 17455], dtype=np.uint16)
        refl = reflectance_from_dn(dn)
        self.assertGreaterEqual(float(refl[0]), 1.0)  # DN=11000 -> reflectancia 1.0
        self.assertGreater(float(refl[1]), 1.6)  # DN=17455 -> reflectancia 1.6455

    def test_mask_counts(self):
        dn = _synthetic_dn(16, 16)
        mask = build_valid_mask(dn)
        n_zero = int(np.count_nonzero(dn == 0))
        n_valid = int(np.count_nonzero(mask))
        self.assertEqual(n_valid, dn.size - n_zero)


class TestCog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.dn = _synthetic_dn(2048, 2048)
        self.crs = rasterio.crs.CRS.from_epsg(32612)
        self.transform = rasterio.transform.from_origin(699960.0, 2900040.0, 10, 10)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_cog_is_real_cog(self):
        refl = apply_mask(reflectance_from_dn(self.dn), build_valid_mask(self.dn))
        path = self.dir / "refl.tif"
        write_cog(path, refl, self.crs, self.transform)
        self.assertTrue(path.is_file())
        with rasterio.open(path) as dst:
            self.assertIn(dst.driver, ("GTiff", "COG"))
            self.assertEqual(dst.width, 2048)
            self.assertEqual(dst.height, 2048)
            self.assertEqual(dst.dtypes[0], "float32")
            self.assertEqual(dst.crs.to_epsg(), 32612)
            self.assertEqual(dst.transform, self.transform)
            self.assertTrue(len(dst.overviews(1)) > 0)
            self.assertTrue(dst.block_shapes[0][0] <= 1024)
            self.assertTrue(math.isnan(float(dst.nodata)))

    def test_cog_roundtrip_values(self):
        dn = np.array([[0, 1000, 10000, 11000], [17455, 5000, 0, 999]], dtype=np.uint16)
        refl = apply_mask(reflectance_from_dn(dn), build_valid_mask(dn))
        path = self.dir / "r.tif"
        write_cog(path, refl, self.crs, self.transform)
        with rasterio.open(path) as dst:
            got = dst.read(1)
        self.assertTrue(math.isnan(float(got[0, 0])))
        self.assertAlmostEqual(float(got[0, 1]), 0.0, places=6)
        self.assertAlmostEqual(float(got[0, 2]), 0.9, places=6)
        self.assertAlmostEqual(float(got[0, 3]), 1.0, places=6)
        self.assertAlmostEqual(float(got[1, 0]), 1.6455, places=6)


class TestDerivedMetadata(unittest.TestCase):
    def test_metadata_validates_contract(self):
        meta = _source_metadata()
        from app.processing.raster import _build_derived_metadata

        out = _build_derived_metadata(
            source_meta=meta,
            derived_id="SENTINEL2_S2MSI2A_20260828T174859_T12RYP_B04_REFL_v1",
            band_name="B04",
            band_variable="red",
            crs="EPSG:32612",
            epsg=32612,
            bounds=[699960.0, 2790240.0, 809760.0, 2900040.0],
            transform=[699960.0, 10.0, 0.0, 2900040.0, 0.0, -10.0],
            width=10980,
            height=10980,
            cog_sha256="a" * 64,
            processing_time="2026-09-06T00:00:00Z",
        )
        self.assertEqual(validate_against_contract(out), [])
        self.assertEqual(out["data_class"], "DERIVED_PRODUCT")
        self.assertEqual(out["data"]["storage"]["format"], "COG")
        self.assertEqual(out["provenance"]["parent_dataset"], meta["identity"]["id"])
        band = out["data"]["raster"]["bands"][0]
        self.assertEqual(band["dtype"], "float32")
        self.assertEqual(band["nodata"], "nan")


class TestDerivedStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalDataStore(Path(self._tmp.name))
        self.meta = _source_metadata()
        self.pid = self.meta["identity"]["id"]

    def tearDown(self):
        self._tmp.cleanup()

    def _put_valid_derived(self):
        self.store.put_derived_metadata(self.pid + "_DERIVED", self.meta)

    def test_put_and_exists_derived(self):
        self.assertFalse(self.store.exists_derived("X_1"))
        self.store.put_derived_metadata("X_1", self.meta)
        self.assertTrue(self.store.exists_derived("X_1"))

    def test_derived_idempotent_and_conflict(self):
        self.store.put_derived_metadata("X_1", self.meta)
        self.store.put_derived_metadata("X_1", copy.deepcopy(self.meta))  # idempotente
        other = copy.deepcopy(self.meta)
        other["quality"]["dataset_quality"]["cloud_cover_percent"] = 1.0
        from app.storage.base import StorageConflictError

        with self.assertRaises(StorageConflictError):
            self.store.put_derived_metadata("X_1", other)

    def test_derived_invalid_rejected(self):
        d = copy.deepcopy(self.meta)
        del d["identity"]
        with self.assertRaises(StorageError):
            self.store.put_derived_metadata("X_1", d)

    def test_derived_file_and_verify(self):
        self.store.put_derived_metadata("X_1", self.meta)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"data")
            src = Path(f.name)
        fm = self.store.put_derived_file("X_1", FileMetadata(filename="a.tif", relative_path="a.tif"), src)
        src.unlink()
        self.assertEqual(fm.sha256, hashlib.sha256(b"data").hexdigest())
        self.assertTrue(self.store.verify_derived("X_1"))
        # tamper
        self.store.get_derived_file("X_1", "a.tif").write_bytes(b"tampered")
        self.assertFalse(self.store.verify_derived("X_1"))

    def test_derived_path_safety(self):
        with self.assertRaises(StorageError):
            self.store.put_derived_metadata("../evil", self.meta)
        self.store.put_derived_metadata("X_1", self.meta)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            src = Path(f.name)
        with self.assertRaises(StorageError):
            self.store.put_derived_file("X_1", FileMetadata(filename="x", relative_path="../out"), src)
        src.unlink()

    def test_derived_atomicity(self):
        with mock.patch("app.storage.local.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.store.put_derived_metadata("X_1", self.meta)
        self.assertFalse(self.store.exists_derived("X_1"))


class TestDeriveIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = LocalDataStore(self.root)
        self.catalog = Catalog(self.root / "catalog.sqlite")
        self.meta = _source_metadata()
        self.source_id = self.meta["identity"]["id"]
        self.store.put_metadata(self.source_id, self.meta)

        # Fuente sintetica (GeoTIFF uint16) en lugar de JP2 real.
        dn = _synthetic_dn(2048, 2048)
        crs = rasterio.crs.CRS.from_epsg(32612)
        transform = rasterio.transform.from_origin(699960.0, 2900040.0, 10, 10)
        self.src_file = self.root / "src.tif"
        with rasterio.open(self.src_file, "w", driver="GTiff", height=2048, width=2048, count=1,
                           dtype="uint16", crs=crs, transform=transform) as dst:
            dst.write(dn, 1)
        fm = FileMetadata(filename="B04_10m.tif", relative_path="B04_10m.tif", media_type="image/tiff", role="data", format="TIFF")
        self.store.put_file(self.source_id, fm, self.src_file)
        self.src_sha = sha256_file(self.src_file)

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def test_derive_full_flow(self):
        derived_id = "SENTINEL2_S2MSI2A_20260828T174859_T12RYP_B04_REFL_v1"
        result = derive_band_reflectance(
            self.store, self.catalog, self.source_id, "B04_10m.tif", derived_id, "B04", "red"
        )
        self.assertTrue(self.store.exists_derived(derived_id))
        self.assertTrue(self.store.get_derived_file(derived_id, result.relative_path).is_file())
        self.assertTrue(self.catalog.exists(derived_id))
        self.assertTrue(self.store.verify_derived(derived_id))
        self.assertEqual(result.cog_sha256, sha256_file(result.cog_path))

        checks = validate_derived_product(
            self.store, self.catalog, self.source_id, "B04_10m.tif",
            derived_id, result.relative_path, expected_crs_epsg=32612,
            expected_width=2048, expected_height=2048, expected_res=(10.0, 10.0),
        )
        failures = [c for c in checks if c["result"] != "PASS"]
        self.assertEqual(failures, [], f"checks con FAIL: {failures}")

    def test_derive_idempotent(self):
        derived_id = "SENTINEL2_S2MSI2A_20260828T174859_T12RYP_B04_REFL_v1"
        r1 = derive_band_reflectance(self.store, self.catalog, self.source_id, "B04_10m.tif", derived_id, "B04", "red")
        r2 = derive_band_reflectance(self.store, self.catalog, self.source_id, "B04_10m.tif", derived_id, "B04", "red")
        self.assertEqual(r1.cog_sha256, r2.cog_sha256)
        self.assertTrue(self.store.verify_derived(derived_id))

    def test_source_not_modified(self):
        derived_id = "SENTINEL2_S2MSI2A_20260828T174859_T12RYP_B04_REFL_v1"
        derive_band_reflectance(self.store, self.catalog, self.source_id, "B04_10m.tif", derived_id, "B04", "red")
        self.assertEqual(sha256_file(self.src_file), self.src_sha)
        self.assertEqual(sha256_file(self.store.get_file(self.source_id, "B04_10m.tif")), self.src_sha)

    def test_no_secrets(self):
        derived_id = "SENTINEL2_S2MSI2A_20260828T174859_T12RYP_B04_REFL_v1"
        derive_band_reflectance(self.store, self.catalog, self.source_id, "B04_10m.tif", derived_id, "B04", "red")
        meta = self.store.get_derived_metadata(derived_id)
        blob = json.dumps(meta).lower()
        for secret in ("token", "password", "secret", "bearer", "client_secret"):
            self.assertNotIn(secret, blob)


if __name__ == "__main__":
    unittest.main()
