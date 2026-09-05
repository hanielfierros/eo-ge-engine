"""Pruebas de integracion del pipeline completo (S-A.12).

Offline; verifican el flujo extremo a extremo, determinismo e idempotencia.

    python -m unittest tests.test_integration_pipeline -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.catalog.adapter import normalized_to_item
from app.catalog.catalog import Catalog
from app.connectors.base import SourceRepresentation
from app.geodata.interface import GeoDataInterface
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.storage.base import FileMetadata
from app.storage.local import LocalDataStore
from app.validators.sentinel2 import Sentinel2Validator

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"

COLLECTION = {"id": "sentinel-2-l2a", "title": "Sentinel-2 L2A", "platform": "sentinel-2", "product": "S2MSI2A"}


def _source_representation() -> SourceRepresentation:
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return SourceRepresentation(
        source=d["source"], product=d["product"], source_id=d["source_id"],
        source_metadata=d["source_metadata"], acquisition=d["acquisition"],
        spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
        checksum=d["checksum"], provenance=d["provenance"],
        collection_metadata=d["collection_metadata"],
    )


class TestIntegrationPipeline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _catalog(self) -> Catalog:
        c = Catalog(self.root / "catalog.sqlite")
        self.addCleanup(c.close)
        return c

    def _store(self) -> LocalDataStore:
        return LocalDataStore(self.root / "storage")

    def test_full_pipeline(self):
        sr = _source_representation()
        metadata = Sentinel2L2ANormalizer().normalize(sr)
        result = Sentinel2Validator().validate(metadata)
        pid = metadata["identity"]["id"]
        self.assertEqual(result.status, "AVAILABLE")

        store = self._store()
        store.put_metadata(pid, metadata)
        catalog = self._catalog()
        catalog.register_collection(COLLECTION)
        catalog.register_item(normalized_to_item(metadata, storage_path=f"storage/normalized/{pid}"))
        geo = GeoDataInterface(catalog, store)

        items = geo.search(collection="sentinel-2-l2a")
        self.assertEqual(len(items), 1)
        self.assertEqual(geo.get_item(pid)["id"], pid)
        self.assertIsNotNone(geo.get_asset(pid, "metadata"))
        self.assertEqual(geo.get_metadata(pid), metadata)
        self.assertTrue(geo.verify(pid))

    def test_deterministic(self):
        a = Sentinel2L2ANormalizer().normalize(_source_representation())
        b = Sentinel2L2ANormalizer().normalize(_source_representation())
        self.assertEqual(a["identity"]["id"], b["identity"]["id"])
        self.assertEqual(a, b)

    def test_idempotent_normalizer(self):
        norm = Sentinel2L2ANormalizer()
        self.assertEqual(norm.normalize(_source_representation()), norm.normalize(_source_representation()))

    def test_idempotent_store(self):
        metadata = Sentinel2L2ANormalizer().normalize(_source_representation())
        pid = metadata["identity"]["id"]
        store = self._store()
        store.put_metadata(pid, metadata)
        store.put_metadata(pid, metadata)
        self.assertTrue(store.exists(pid))

    def test_idempotent_catalog(self):
        metadata = Sentinel2L2ANormalizer().normalize(_source_representation())
        pid = metadata["identity"]["id"]
        catalog = self._catalog()
        catalog.register_collection(COLLECTION)
        item = normalized_to_item(metadata, storage_path=f"storage/normalized/{pid}")
        catalog.register_item(item)
        catalog.register_item(json.loads(json.dumps(item)))
        self.assertEqual(len(catalog.search(collection="sentinel-2-l2a")), 1)

    def test_full_flow_with_file(self):
        metadata = Sentinel2L2ANormalizer().normalize(_source_representation())
        pid = metadata["identity"]["id"]
        store = self._store()
        store.put_metadata(pid, metadata)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jp2") as f:
            f.write(b"band data")
            src = Path(f.name)
        store.put_file(pid, FileMetadata(filename="B04_10m.jp2", relative_path="B04_10m.jp2"), src)
        src.unlink()

        catalog = self._catalog()
        catalog.register_collection(COLLECTION)
        catalog.register_item(normalized_to_item(metadata, storage_path=f"storage/normalized/{pid}"))
        geo = GeoDataInterface(catalog, store)
        self.assertTrue(geo.get_file(pid, "B04_10m.jp2").exists())
        self.assertTrue(geo.verify(pid))


if __name__ == "__main__":
    unittest.main()
