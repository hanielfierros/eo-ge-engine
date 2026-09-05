"""Tests de la GeoData Interface (S-A.11).

Offline; usan la fixture de Sentinel-2, un LocalDataStore y un Catalog temporales.

    python -m unittest tests.test_geodata_interface -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.catalog.adapter import normalized_to_item
from app.catalog.catalog import Catalog
from app.connectors.base import SourceRepresentation
from app.geodata.interface import (
    AssetNotFoundError,
    GeoDataInterface,
    ItemNotFoundError,
    MetadataNotFoundError,
    StorageReferenceError,
)
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.storage.base import FileMetadata, StorageError
from app.storage.local import LocalDataStore

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"

COLLECTION = {"id": "sentinel-2-l2a", "title": "Sentinel-2 L2A", "platform": "sentinel-2", "product": "S2MSI2A"}


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


class _GeoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalDataStore(Path(self._tmp.name) / "storage")
        self.catalog = Catalog(Path(self._tmp.name) / "catalog.sqlite")
        self.interface = GeoDataInterface(self.catalog, self.store)

        self.meta = _metadata()
        self.pid = self.meta["identity"]["id"]
        self.store.put_metadata(self.pid, self.meta)
        self.catalog.register_collection(COLLECTION)
        self.catalog.register_item(normalized_to_item(self.meta, storage_path=f"storage/normalized/{self.pid}"))

        # archivo cientifico de prueba
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jp2") as f:
            f.write(b"band data")
            self._src = Path(f.name)
        self.store.put_file(self.pid, FileMetadata(filename="B04_10m.jp2", relative_path="B04_10m.jp2"), self._src)

    def tearDown(self):
        self._src.unlink(missing_ok=True)
        self.catalog.close()
        self._tmp.cleanup()


class TestSearch(_GeoTest):
    def test_by_collection(self):
        self.assertEqual(len(self.interface.search(collection="sentinel-2-l2a")), 1)

    def test_by_datetime(self):
        r = self.interface.search(datetime="2026-08-28T17:48:59.024000Z")
        self.assertEqual(len(r), 1)

    def test_by_platform(self):
        self.assertEqual(len(self.interface.search(platform="sentinel-2b")), 1)

    def test_by_product(self):
        self.assertEqual(len(self.interface.search(product="S2MSI2A")), 1)

    def test_by_validation_status(self):
        self.assertEqual(len(self.interface.search(validation_status="AVAILABLE")), 1)

    def test_by_bbox(self):
        self.assertEqual(len(self.interface.search(bbox=(-108.5, 25.4, -108.3, 25.6))), 1)

    def test_no_results(self):
        self.assertEqual(len(self.interface.search(collection="nope")), 0)


class TestItems(_GeoTest):
    def test_get_item(self):
        item = self.interface.get_item(self.pid)
        self.assertEqual(item["id"], self.pid)

    def test_get_item_missing(self):
        with self.assertRaises(ItemNotFoundError):
            self.interface.get_item("NOT_EXIST")

    def test_deterministic_id(self):
        item = self.interface.get_item(self.pid)
        self.assertEqual(item["id"], self.meta["identity"]["id"])


class TestMetadata(_GeoTest):
    def test_get_metadata(self):
        m = self.interface.get_metadata(self.pid)
        self.assertEqual(m, self.meta)

    def test_get_metadata_missing(self):
        with self.assertRaises(MetadataNotFoundError):
            self.interface.get_metadata("NOT_EXIST")

    def test_metadata_preserved(self):
        m = self.interface.get_metadata(self.pid)
        self.assertEqual(m["identity"]["id"], self.pid)
        self.assertEqual(m["quality"]["dataset_quality"]["cloud_cover_percent"], 20.24)


class TestAssets(_GeoTest):
    def test_get_asset(self):
        a = self.interface.get_asset(self.pid, "metadata")
        self.assertEqual(a["role"], "metadata")

    def test_get_asset_missing(self):
        with self.assertRaises(AssetNotFoundError):
            self.interface.get_asset(self.pid, "nope")

    def test_get_asset_invalid_item(self):
        with self.assertRaises(ItemNotFoundError):
            self.interface.get_asset("NOT_EXIST", "metadata")


class TestFiles(_GeoTest):
    def test_get_file(self):
        p = self.interface.get_file(self.pid, "B04_10m.jp2")
        self.assertTrue(p.is_file())

    def test_get_file_missing(self):
        with self.assertRaises(StorageReferenceError):
            self.interface.get_file(self.pid, "nope.jp2")

    def test_path_traversal_rejected(self):
        with self.assertRaises(StorageError):
            self.interface.get_file(self.pid, "../evil")


class TestIntegrity(_GeoTest):
    def test_verify_ok(self):
        self.assertTrue(self.interface.verify(self.pid))

    def test_verify_modified(self):
        p = self.interface.get_file(self.pid, "B04_10m.jp2")
        p.write_bytes(b"tampered")
        self.assertFalse(self.interface.verify(self.pid))

    def test_verify_deleted(self):
        p = self.interface.get_file(self.pid, "B04_10m.jp2")
        p.unlink()
        self.assertFalse(self.interface.verify(self.pid))

    def test_exists(self):
        self.assertTrue(self.interface.exists(self.pid))
        self.assertFalse(self.interface.exists("NOT_EXIST"))


class TestArchitecture(_GeoTest):
    def test_search_delegates_to_catalog(self):
        with mock.patch.object(self.catalog, "search", return_value=[]) as m:
            self.interface.search(collection="x")
            m.assert_called_once()

    def test_verify_delegates_to_store(self):
        with mock.patch.object(self.store, "verify", return_value=True) as m:
            self.interface.verify(self.pid)
            m.assert_called_once()

    def test_no_sql_in_interface(self):
        src = (ROOT / "app" / "geodata" / "interface.py").read_text(encoding="utf-8")
        for keyword in ("SELECT", "INSERT", "CREATE TABLE", "UPDATE", "DELETE"):
            self.assertNotIn(keyword, src)


class TestEndToEnd(_GeoTest):
    def test_full_flow(self):
        items = self.interface.search(collection="sentinel-2-l2a")
        self.assertEqual(len(items), 1)
        item = self.interface.get_item(self.pid)
        self.assertEqual(item["id"], self.pid)
        asset = self.interface.get_asset(self.pid, "metadata")
        self.assertIsNotNone(asset)
        metadata = self.interface.get_metadata(self.pid)
        self.assertEqual(metadata, self.meta)
        f = self.interface.get_file(self.pid, "B04_10m.jp2")
        self.assertTrue(f.exists())
        self.assertTrue(self.interface.verify(self.pid))


if __name__ == "__main__":
    unittest.main()
