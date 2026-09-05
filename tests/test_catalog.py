"""Tests del Catalog (S-A.10).

Offline; usan SQLite temporal y la fixture de Source Representation.

    python -m unittest tests.test_catalog -v
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.catalog.adapter import normalized_to_item
from app.catalog.catalog import Catalog, CatalogIdConflictError, CatalogPathError
from app.connectors.base import SourceRepresentation
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"


def _metadata() -> dict:
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sr = SourceRepresentation(
        source=d["source"], product=d["product"], source_id=d["source_id"],
        source_metadata=d["source_metadata"], acquisition=d["acquisition"],
        spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
        checksum=d["checksum"], provenance=d["provenance"],
        collection_metadata=d["collection_metadata"],
    )
    return Sentinel2L2ANormalizer().normalize(sr)


COLLECTION = {
    "id": "sentinel-2-l2a",
    "title": "Sentinel-2 Level-2A",
    "description": "Sentinel-2 surface reflectance",
    "platform": "sentinel-2",
    "product": "S2MSI2A",
    "version": "1",
}


class _CatalogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog = Catalog(Path(self._tmp.name) / "catalog.sqlite")
        self.meta = _metadata()

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def _register_item(self):
        self.catalog.register_collection(COLLECTION)
        item = normalized_to_item(self.meta, storage_path="storage/normalized/X")
        self.catalog.register_item(item)
        return item


class TestSchemaAndRegister(_CatalogTest):
    def test_create_and_schema(self):
        tables = self.catalog._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in tables}
        self.assertTrue({"collections", "items", "assets"} <= names)

    def test_register_collection(self):
        cid = self.catalog.register_collection(COLLECTION)
        self.assertEqual(cid, "sentinel-2-l2a")

    def test_register_item_and_assets(self):
        item = self._register_item()
        got = self.catalog.get_item(item["id"])
        self.assertIsNotNone(got)
        self.assertGreaterEqual(len(got["assets"]), 1)

    def test_get_assets(self):
        item = self._register_item()
        got = self.catalog.get_item(item["id"])
        keys = [a["asset_key"] for a in got["assets"]]
        self.assertIn("metadata", keys)

    def test_item_stac_compatible(self):
        item = normalized_to_item(self.meta, storage_path="storage/normalized/X")
        self.assertEqual(item["collection_id"], "sentinel-2-l2a")
        self.assertEqual(item["datetime"], "2026-08-28T17:48:59.024000Z")
        self.assertIsNotNone(item["bbox"])
        self.assertIsNotNone(item["geometry"])

    def test_deterministic_id(self):
        item = normalized_to_item(self.meta)
        self.assertEqual(item["id"], self.meta["identity"]["id"])


class TestIdempotencyAndConflict(_CatalogTest):
    def test_idempotent(self):
        self.catalog.register_collection(COLLECTION)
        item = normalized_to_item(self.meta, storage_path="storage/normalized/X")
        self.catalog.register_item(item)
        self.catalog.register_item(copy.deepcopy(item))  # no duplicado
        self.assertEqual(len(self.catalog.search(collection="sentinel-2-l2a")), 1)

    def test_conflict(self):
        self.catalog.register_collection(COLLECTION)
        item = normalized_to_item(self.meta, storage_path="storage/normalized/X")
        self.catalog.register_item(item)
        other = copy.deepcopy(item)
        other["datetime"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(CatalogIdConflictError):
            self.catalog.register_item(other)


class TestSearch(_CatalogTest):
    def setUp(self):
        super().setUp()
        self.catalog.register_collection(COLLECTION)
        self.catalog.register_item(normalized_to_item(self.meta, storage_path="storage/normalized/X"))

    def test_by_collection(self):
        self.assertEqual(len(self.catalog.search(collection="sentinel-2-l2a")), 1)
        self.assertEqual(len(self.catalog.search(collection="other")), 0)

    def test_by_datetime_range(self):
        r = self.catalog.search(datetime_start="2026-08-01T00:00:00Z", datetime_end="2026-09-01T00:00:00Z")
        self.assertEqual(len(r), 1)
        r = self.catalog.search(datetime_start="2027-01-01T00:00:00Z")
        self.assertEqual(len(r), 0)

    def test_by_platform(self):
        self.assertEqual(len(self.catalog.search(platform="sentinel-2b")), 1)

    def test_by_validation_status(self):
        self.assertEqual(len(self.catalog.search(validation_status="AVAILABLE")), 1)

    def test_by_bbox(self):
        r = self.catalog.search(bbox=(-108.5, 25.4, -108.3, 25.6))
        self.assertEqual(len(r), 1)
        r = self.catalog.search(bbox=(-200.0, -200.0, -199.0, -199.0))
        self.assertEqual(len(r), 0)


class TestRemoveAndRollback(_CatalogTest):
    def test_remove(self):
        self.catalog.register_collection(COLLECTION)
        item = normalized_to_item(self.meta, storage_path="storage/normalized/X")
        self.catalog.register_item(item)
        self.catalog.remove_item(item["id"])
        self.assertFalse(self.catalog.exists(item["id"]))

    def test_transaction_rollback_on_bad_asset(self):
        self.catalog.register_collection(COLLECTION)
        item = normalized_to_item(self.meta, storage_path="storage/normalized/X")
        item["assets"].append({"asset_key": "evil", "href": "../outside", "role": "data"})
        with self.assertRaises(CatalogPathError):
            self.catalog.register_item(item)
        # el item no quedo parcialmente registrado
        self.assertFalse(self.catalog.exists(item["id"]))


class TestPathSafety(_CatalogTest):
    def test_storage_path_traversal(self):
        self.catalog.register_collection(COLLECTION)
        item = normalized_to_item(self.meta, storage_path="../evil")
        with self.assertRaises(CatalogPathError):
            self.catalog.register_item(item)

    def test_storage_path_absolute(self):
        self.catalog.register_collection(COLLECTION)
        item = normalized_to_item(self.meta, storage_path="C:/evil")
        with self.assertRaises(CatalogPathError):
            self.catalog.register_item(item)


class TestIntegration(_CatalogTest):
    def test_data_store_to_catalog(self):
        from app.storage.local import LocalDataStore
        from app.validators.sentinel2 import Sentinel2Validator

        validator = Sentinel2Validator()
        result = validator.validate(self.meta)
        self.assertEqual(result.status, "AVAILABLE")

        with tempfile.TemporaryDirectory() as tmp:
            store = LocalDataStore(Path(tmp))
            store.put_metadata(self.meta["identity"]["id"], self.meta)

            storage_path = f"storage/normalized/{self.meta['identity']['id']}"
            self.catalog.register_collection(COLLECTION)
            self.catalog.register_item(normalized_to_item(self.meta, storage_path=storage_path))

            items = self.catalog.search(collection="sentinel-2-l2a")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["storage_path"], storage_path)
            self.assertEqual(items[0]["id"], self.meta["identity"]["id"])
            self.assertTrue(store.verify(self.meta["identity"]["id"]))


if __name__ == "__main__":
    unittest.main()
