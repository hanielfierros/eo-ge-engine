"""Pruebas adversariales y de seguridad (S-A.12).

Corrupcion/recuperacion, path traversal agresivo, ausencia de secretos y
pureza offline de la suite.

    python -m unittest tests.test_adversarial -v
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from app.catalog.catalog import Catalog
from app.catalog.adapter import normalized_to_item
from app.connectors.base import SourceRepresentation
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.storage.base import FileMetadata, StorageError
from app.storage.local import LocalDataStore

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


class TestCorruptionAndRecovery(unittest.TestCase):
    def test_verify_pass_fail_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalDataStore(Path(tmp))
            meta = _metadata()
            pid = meta["identity"]["id"]
            store.put_metadata(pid, meta)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jp2") as f:
                f.write(b"valid data")
                src = Path(f.name)
            store.put_file(pid, FileMetadata(filename="a.jp2", relative_path="a.jp2"), src)
            src.unlink()

            self.assertTrue(store.verify(pid))  # PASS
            fpath = store.get_file(pid, "a.jp2")
            fpath.write_bytes(b"corrupted")  # modificacion artificial
            self.assertFalse(store.verify(pid))  # FAIL
            fpath.write_bytes(b"valid data")  # restaurar
            self.assertTrue(store.verify(pid))  # PASS de nuevo


class TestAggressivePathTraversal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalDataStore(Path(self._tmp.name))
        self.meta = _metadata()
        self.pid = self.meta["identity"]["id"]
        self.store.put_metadata(self.pid, self.meta)

    def tearDown(self):
        self._tmp.cleanup()

    def test_id_dotdot(self):
        with self.assertRaises(StorageError):
            self.store.put_metadata("../evil", self.meta)

    def test_id_dotdotdotdot(self):
        with self.assertRaises(StorageError):
            self.store.put_metadata("../../evil", self.meta)

    def test_relative_path_backslash(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            src = Path(f.name)
        with self.assertRaises(StorageError):
            self.store.put_file(self.pid, FileMetadata(filename="x", relative_path="..\\outside"), src)
        src.unlink()

    def test_relative_path_drive(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            src = Path(f.name)
        with self.assertRaises(StorageError):
            self.store.put_file(self.pid, FileMetadata(filename="x", relative_path="C:/evil"), src)
        src.unlink()


class TestNoSecretLeak(unittest.TestCase):
    _PATTERNS = [
        re.compile(r"BEGIN (RSA|EC|OPENSSH) PRIVATE KEY"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"ghp_[0-9A-Za-z]{20,}"),
        re.compile(r"password\s*=\s*['\"][^'\"]+['\"]"),
        re.compile(r"api_key\s*=\s*['\"][^'\"]+['\"]"),
        re.compile(r"secret\s*=\s*['\"][^'\"]+['\"]"),
        re.compile(r"Authorization:\s*Bearer\s+[0-9A-Za-z._-]{20,}"),
    ]

    def test_no_secrets_in_code(self):
        violations = []
        for path in (ROOT / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for pat in self._PATTERNS:
                if pat.search(text):
                    violations.append((str(path), pat.pattern))
        self.assertEqual(violations, [])

    def test_no_secrets_in_fixtures_and_config(self):
        violations = []
        targets = [(ROOT / "tests" / "fixtures").rglob("*.json")]
        targets.append((ROOT / "config").glob("*.json"))
        for group in targets:
            for path in group:
                text = path.read_text(encoding="utf-8", errors="replace")
                for pat in self._PATTERNS:
                    if pat.search(text):
                        violations.append((str(path), pat.pattern))
        self.assertEqual(violations, [])


class TestOfflinePurity(unittest.TestCase):
    def test_tests_do_not_use_network_directly(self):
        # Ningun archivo de test debe invocar requests.* directamente (sin mock).
        pattern = re.compile(r"(?<!mock\.)requests\.(get|post|put|delete|request)\(")
        violations = []
        for path in (ROOT / "tests").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                violations.append(str(path))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
