"""Tests del Data Store local (S-A.9).

No descargan datos reales; usan la fixture de Source Representation y un
directorio temporal como raiz del almacen.

    python -m unittest tests.test_local_data_store -v
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.connectors.base import SourceRepresentation
from app.normalizers.base import validate_against_contract
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.storage.base import FileMetadata, StorageConflictError, StorageError, StorageNotFoundError
from app.storage.local import LocalDataStore

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"


def _valid_metadata() -> dict:
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sr = SourceRepresentation(
        source=d["source"], product=d["product"], source_id=d["source_id"],
        source_metadata=d["source_metadata"], acquisition=d["acquisition"],
        spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
        checksum=d["checksum"], provenance=d["provenance"],
        collection_metadata=d["collection_metadata"],
    )
    return Sentinel2L2ANormalizer().normalize(sr)


class _StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalDataStore(Path(self._tmp.name))
        self.meta = _valid_metadata()
        self.pid = self.meta["identity"]["id"]

    def tearDown(self):
        self._tmp.cleanup()


class TestMetadata(_StoreTest):
    def test_create_and_exists(self):
        self.assertFalse(self.store.exists(self.pid))
        self.store.put_metadata(self.pid, self.meta)
        self.assertTrue(self.store.exists(self.pid))

    def test_roundtrip_and_schema(self):
        self.store.put_metadata(self.pid, self.meta)
        loaded = self.store.get_metadata(self.pid)
        self.assertEqual(loaded, self.meta)
        self.assertEqual(validate_against_contract(loaded), [])

    def test_delete(self):
        self.store.put_metadata(self.pid, self.meta)
        self.store.delete(self.pid)
        self.assertFalse(self.store.exists(self.pid))

    def test_delete_missing(self):
        with self.assertRaises(StorageNotFoundError):
            self.store.delete("NOT_EXIST")


class TestDuplicatesAndConflicts(_StoreTest):
    def test_duplicate_idempotent(self):
        self.store.put_metadata(self.pid, self.meta)
        self.store.put_metadata(self.pid, copy.deepcopy(self.meta))  # no error, idempotente
        self.assertTrue(self.store.exists(self.pid))

    def test_conflict(self):
        self.store.put_metadata(self.pid, self.meta)
        other = copy.deepcopy(self.meta)
        other["quality"]["dataset_quality"]["cloud_cover_percent"] = 99.0
        with self.assertRaises(StorageConflictError):
            self.store.put_metadata(self.pid, other)


class TestInvalidRejected(_StoreTest):
    def test_invalid_rejected(self):
        d = copy.deepcopy(self.meta)
        del d["identity"]
        with self.assertRaises(StorageError):
            self.store.put_metadata(self.pid, d)

    def test_partial_stored(self):
        d = copy.deepcopy(self.meta)
        d["provenance"].pop("checksum", None)  # schema-valid, PARTIAL
        self.store.put_metadata(self.pid, d)
        self.assertTrue(self.store.exists(self.pid))


class TestFiles(_StoreTest):
    def test_put_and_verify_file(self):
        self.store.put_metadata(self.pid, self.meta)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jp2") as f:
            f.write(b"fake jp2 data")
            src = Path(f.name)
        fm = self.store.put_file(self.pid, FileMetadata(filename="x.jp2", relative_path="x.jp2"), src)
        src.unlink()
        self.assertEqual(fm.sha256, hashlib.sha256(b"fake jp2 data").hexdigest())
        self.assertEqual(fm.size, len(b"fake jp2 data"))
        self.assertTrue(self.store.verify(self.pid))

    def test_modified_file_detected(self):
        self.store.put_metadata(self.pid, self.meta)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jp2") as f:
            f.write(b"original")
            src = Path(f.name)
        self.store.put_file(self.pid, FileMetadata(filename="a.jp2", relative_path="a.jp2"), src)
        src.unlink()
        self.assertTrue(self.store.verify(self.pid))
        # modificar el archivo guardado
        dest = self.store.get_file(self.pid, "a.jp2")
        dest.write_bytes(b"tampered")
        self.assertFalse(self.store.verify(self.pid))

    def test_deleted_file_detected(self):
        self.store.put_metadata(self.pid, self.meta)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"data")
            src = Path(f.name)
        self.store.put_file(self.pid, FileMetadata(filename="a.bin", relative_path="a.bin"), src)
        src.unlink()
        self.store.get_file(self.pid, "a.bin").unlink()
        self.assertFalse(self.store.verify(self.pid))


class TestPathSafety(_StoreTest):
    def test_id_traversal(self):
        with self.assertRaises(StorageError):
            self.store.put_metadata("../evil", self.meta)

    def test_relative_path_absolute(self):
        self.store.put_metadata(self.pid, self.meta)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            src = Path(f.name)
        with self.assertRaises(StorageError):
            self.store.put_file(self.pid, FileMetadata(filename="x", relative_path="/etc/passwd"), src)
        src.unlink()

    def test_relative_path_traversal(self):
        self.store.put_metadata(self.pid, self.meta)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            src = Path(f.name)
        with self.assertRaises(StorageError):
            self.store.put_file(self.pid, FileMetadata(filename="x", relative_path="../outside"), src)
        src.unlink()


class TestAtomicity(_StoreTest):
    def test_write_failure_no_corruption(self):
        with mock.patch("app.storage.local.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.store.put_metadata(self.pid, self.meta)
        self.assertFalse(self.store.exists(self.pid))
        # staging se puede limpiar
        self.assertGreaterEqual(self.store.cleanup_staging(), 0)

    def test_cleanup_staging(self):
        # simular staging abandonado
        (self.store.staging / "X_1").mkdir(parents=True)
        removed = self.store.cleanup_staging()
        self.assertGreaterEqual(removed, 1)


class TestEndToEnd(_StoreTest):
    def test_full_flow_offline(self):
        from app.validators.sentinel2 import Sentinel2Validator

        validator = Sentinel2Validator()
        result = validator.validate(self.meta)
        self.assertEqual(result.status, "AVAILABLE")

        self.store.put_metadata(self.pid, self.meta)
        loaded = self.store.get_metadata(self.pid)
        self.assertEqual(validate_against_contract(loaded), [])
        self.assertTrue(self.store.verify(self.pid))

        # determinismo
        self.assertEqual(self.store.get_metadata(self.pid), self.meta)


if __name__ == "__main__":
    unittest.main()
