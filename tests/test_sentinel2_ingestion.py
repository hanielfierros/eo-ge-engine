"""Tests de ingesta Sentinel-2 (S-A.15).

Offline salvo el test marcado EXTERNAL_INTEGRATION, que requiere
EO_GE_REAL_INGEST=1 y CDSE_TOKEN.

    python -m unittest tests.test_sentinel2_ingestion -v
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.catalog.catalog import Catalog
from app.connectors.base import AuthenticationError, IntegrityError, SourceReference
from app.connectors.sentinel2 import Sentinel2L2AConnector
from app.geodata.interface import GeoDataInterface
from app.ingest.sentinel2 import JP2_SIGNATURE, ingest_sentinel2_asset, looks_like_jp2
from app.storage.local import LocalDataStore

ROOT = Path(__file__).resolve().parent.parent
ITEM_FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_item.json"
SR_FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"


def _load_item() -> dict:
    return json.loads(ITEM_FIXTURE.read_text(encoding="utf-8"))


def _collection_metadata() -> dict:
    return json.loads(SR_FIXTURE.read_text(encoding="utf-8"))["collection_metadata"]


def _ref() -> SourceReference:
    item = _load_item()
    # T12RYP es UTM 12N. No forzar EPSG:32613 (CRS de analisis de Sinaloa).
    item["properties"]["proj:epsg"] = None
    item["properties"]["grid:code"] = "T12RYP"
    return SourceReference(source_id=item["id"], collection=item["collection"], item=item)


def _jp2_bytes(payload: bytes = b"unit-test-payload") -> bytes:
    return JP2_SIGNATURE + payload


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content

    def iter_content(self, chunk_size=65536):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestJp2Magic(unittest.TestCase):
    def test_magic_detects_jp2(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(_jp2_bytes())
            p = Path(f.name)
        self.assertTrue(looks_like_jp2(p))
        p.unlink()

    def test_magic_rejects_html(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"<html>login</html>")
            p = Path(f.name)
        self.assertFalse(looks_like_jp2(p))
        p.unlink()


class TestIngestOffline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = LocalDataStore(self.root / "storage")
        self.catalog = Catalog(self.root / "catalog.sqlite")
        self.conn = Sentinel2L2AConnector(token="UNITTEST_PLACEHOLDER_TOKEN_VALUE")

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def _ingest(self, content: bytes | None = None, ref: SourceReference | None = None, asset_name: str = "B04_10m"):
        payload = content if content is not None else _jp2_bytes()
        fake = _FakeResponse(status_code=200, content=payload)
        with mock.patch.object(self.conn._session, "get", return_value=fake):
            return ingest_sentinel2_asset(
                ref or _ref(),
                self.store,
                self.catalog,
                asset_name=asset_name,
                connector=self.conn,
                collection_metadata=_collection_metadata(),
                require_jp2_magic=True,
            )

    def test_ingest_stores_and_catalogues(self):
        payload = _jp2_bytes(b"B04-offline")
        result = self._ingest(payload)
        self.assertEqual(result.asset_id, "B04_10m")
        self.assertEqual(result.checksum, hashlib.sha256(payload).hexdigest())
        self.assertEqual(result.checksum_verification, "SHA-256_LOCAL")
        self.assertFalse(result.raster_check["scaling_applied"])
        self.assertTrue(self.store.exists(result.item_id))
        geo = GeoDataInterface(self.catalog, self.store)
        self.assertTrue(geo.exists(result.item_id))
        self.assertTrue(geo.verify(result.item_id))
        asset = geo.get_asset(result.item_id, "B04_10m")
        self.assertIsNotNone(asset["href"])
        path = geo.get_file(result.item_id, "B04_10m.jp2")
        self.assertTrue(path.is_file())
        self.assertEqual(sha_of(path), result.checksum)
        self.assertNotIn("UNITTEST_PLACEHOLDER_TOKEN_VALUE", json.dumps(geo.get_metadata(result.item_id)))

    def test_ingest_idempotent(self):
        payload = _jp2_bytes(b"same")
        a = self._ingest(payload)
        b = self._ingest(payload)
        self.assertEqual(a.checksum, b.checksum)
        self.assertEqual(a.item_id, b.item_id)
        self.assertTrue(b.reused)
        rows = self.catalog._conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()
        self.assertEqual(rows["n"], 1)
        files = list((self.store.normalized / a.item_id / "files").glob("B04_10m.jp2"))
        self.assertEqual(len(files), 1)

    def test_partial_then_complete(self):
        ref = _ref()
        dest_dir = self.store.source_cache / ref.source_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        partial = dest_dir / "B04_10m.jp2.part"
        partial.write_bytes(b"truncated")
        result = self._ingest(_jp2_bytes(b"complete"))
        self.assertFalse(partial.exists())
        self.assertGreater(result.size_bytes, 0)
        self.assertTrue(looks_like_jp2(Path(result.source_cache_path)))

    def test_corrupt_normalized_restored_from_cache(self):
        first = self._ingest(_jp2_bytes(b"v1"))
        stored = self.store.get_file(first.item_id, "B04_10m.jp2")
        stored.write_bytes(b"not-a-jp2-corrupt")
        second = self._ingest(_jp2_bytes(b"v1"))
        self.assertEqual(second.item_id, first.item_id)
        self.assertEqual(second.checksum, first.checksum)
        self.assertTrue(looks_like_jp2(self.store.get_file(second.item_id, "B04_10m.jp2")))

    def test_corrupt_cache_redownloaded(self):
        first = self._ingest(_jp2_bytes(b"v1"))
        Path(first.source_cache_path).write_bytes(b"not-a-jp2-corrupt")
        stored = self.store.get_file(first.item_id, "B04_10m.jp2")
        stored.write_bytes(b"not-a-jp2-corrupt")
        second = self._ingest(_jp2_bytes(b"v2-repaired"))
        self.assertEqual(second.item_id, first.item_id)
        self.assertTrue(looks_like_jp2(self.store.get_file(second.item_id, "B04_10m.jp2")))
        self.assertNotEqual(second.checksum, first.checksum)

    def test_reject_non_jp2(self):
        fake = _FakeResponse(status_code=200, content=b"<html>not raster</html>")
        with mock.patch.object(self.conn._session, "get", return_value=fake):
            with self.assertRaises(IntegrityError):
                ingest_sentinel2_asset(
                    _ref(),
                    self.store,
                    self.catalog,
                    asset_name="B04_10m",
                    connector=self.conn,
                    collection_metadata=_collection_metadata(),
                )
        self.assertEqual(len(self.catalog.search(collection="sentinel-2-l2a")), 0)

    def test_oidc_required_without_token(self):
        conn = Sentinel2L2AConnector(token=None)
        ref = _ref()
        ref.item["assets"]["B04_10m"]["href"] = "s3://eodata/Sentinel-2/B04.jp2"
        ref.item["assets"]["B04_10m"]["alternate"] = {
            "https": {
                "href": "https://download.dataspace.copernicus.eu/odata/v1/Products(x)/$value",
                "auth:refs": ["oidc"],
            }
        }
        with self.assertRaises(AuthenticationError) as ctx:
            ingest_sentinel2_asset(
                ref,
                self.store,
                self.catalog,
                asset_name="B04_10m",
                connector=conn,
                collection_metadata=_collection_metadata(),
                require_jp2_magic=False,
            )
        self.assertNotIn("UNITTEST_PLACEHOLDER_TOKEN_VALUE", str(ctx.exception))

    def test_native_crs_from_tile_not_forced_32613(self):
        result = self._ingest(_jp2_bytes())
        meta = self.store.get_metadata(result.item_id)
        self.assertEqual(meta["spatial"]["epsg"], 32612)
        self.assertEqual(meta["spatial"]["crs"], "EPSG:32612")


class TestMultiAssetIngest(unittest.TestCase):
    """S-A.15.1: un Item, varios assets. Offline. No toca el B04 real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = LocalDataStore(self.root / "storage")
        self.catalog = Catalog(self.root / "catalog.sqlite")
        self.conn = Sentinel2L2AConnector(token="UNITTEST_PLACEHOLDER_TOKEN_VALUE")

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def _ingest(self, content: bytes | None = None, ref: SourceReference | None = None, asset_name: str = "B04_10m"):
        payload = content if content is not None else _jp2_bytes()
        fake = _FakeResponse(status_code=200, content=payload)
        with mock.patch.object(self.conn._session, "get", return_value=fake):
            return ingest_sentinel2_asset(
                ref or _ref(),
                self.store,
                self.catalog,
                asset_name=asset_name,
                connector=self.conn,
                collection_metadata=_collection_metadata(),
                require_jp2_magic=True,
            )

    def _keys(self, item_id: str) -> list[str]:
        item = self.catalog.get_item(item_id)
        return [a.get("asset_key") for a in item["assets"] if a.get("role") == "data"]

    def test_first_asset_b04(self):
        result = self._ingest(_jp2_bytes(b"B04-a"), asset_name="B04_10m")
        self.assertEqual(result.asset_id, "B04_10m")
        keys = self._keys(result.item_id)
        self.assertIn("B04_10m", keys)
        self.assertNotIn("B08_10m", keys)
        self.assertTrue(self.store.get_file(result.item_id, "B04_10m.jp2").is_file())
        self.assertIsNone(self.store.get_file(result.item_id, "B08_10m.jp2"))

    def test_second_asset_b08_preserves_b04(self):
        b04 = self._ingest(_jp2_bytes(b"B04-keep"), asset_name="B04_10m")
        sha_b04 = b04.checksum
        b08 = self._ingest(_jp2_bytes(b"B08-add"), asset_name="B08_10m")
        self.assertEqual(b08.item_id, b04.item_id)
        keys = self._keys(b04.item_id)
        self.assertIn("B04_10m", keys)
        self.assertIn("B08_10m", keys)
        self.assertEqual(sha_of(self.store.get_file(b04.item_id, "B04_10m.jp2")), sha_b04)
        self.assertTrue(self.store.get_file(b04.item_id, "B08_10m.jp2").is_file())
        bands = [b["name"] for b in self.store.get_metadata(b04.item_id)["data"]["raster"]["bands"]]
        self.assertIn("B04", bands)
        self.assertIn("B08", bands)
        geo = GeoDataInterface(self.catalog, self.store)
        self.assertTrue(geo.verify(b04.item_id))
        self.assertTrue(geo.get_file(b04.item_id, "B04_10m.jp2").is_file())
        self.assertTrue(geo.get_file(b04.item_id, "B08_10m.jp2").is_file())

    def test_idempotent_b04_keeps_b08(self):
        b04_payload = _jp2_bytes(b"B04-idemp")
        b08_payload = _jp2_bytes(b"B08-idemp")
        first = self._ingest(b04_payload, asset_name="B04_10m")
        self._ingest(b08_payload, asset_name="B08_10m")
        again = self._ingest(b04_payload, asset_name="B04_10m")
        self.assertTrue(again.reused)
        self.assertEqual(again.checksum, first.checksum)
        keys = self._keys(first.item_id)
        self.assertEqual(keys.count("B04_10m"), 1)
        self.assertIn("B08_10m", keys)
        files = list((self.store.normalized / first.item_id / "files").glob("B04_10m.jp2"))
        self.assertEqual(len(files), 1)

    def test_idempotent_b08_keeps_b04(self):
        b04_payload = _jp2_bytes(b"B04-stay")
        b08_payload = _jp2_bytes(b"B08-twice")
        first = self._ingest(b04_payload, asset_name="B04_10m")
        self._ingest(b08_payload, asset_name="B08_10m")
        again = self._ingest(b08_payload, asset_name="B08_10m")
        self.assertTrue(again.reused)
        keys = self._keys(first.item_id)
        self.assertIn("B04_10m", keys)
        self.assertEqual(keys.count("B08_10m"), 1)
        self.assertEqual(sha_of(self.store.get_file(first.item_id, "B04_10m.jp2")), hashlib.sha256(b04_payload).hexdigest())

    def test_second_asset_failure_preserves_b04(self):
        b04 = self._ingest(_jp2_bytes(b"B04-safe"), asset_name="B04_10m")
        pid = b04.item_id
        sha_b04 = b04.checksum
        with mock.patch.object(self.store, "put_file", side_effect=IntegrityError("fallo controlado B08")):
            with self.assertRaises(IntegrityError):
                self._ingest(_jp2_bytes(b"B08-fail"), asset_name="B08_10m")
        self.assertTrue(self.store.exists(pid))
        self.assertTrue(self.store.verify(pid))
        self.assertEqual(sha_of(self.store.get_file(pid, "B04_10m.jp2")), sha_b04)
        self.assertIsNone(self.store.get_file(pid, "B08_10m.jp2"))
        self.assertIn("B04_10m", self._keys(pid))
        self.assertNotIn("B08_10m", self._keys(pid))

    def test_asset_integrity_metadata(self):
        b04 = self._ingest(_jp2_bytes(b"B04-meta"), asset_name="B04_10m")
        b08 = self._ingest(_jp2_bytes(b"B08-meta"), asset_name="B08_10m")
        geo = GeoDataInterface(self.catalog, self.store)
        a04 = geo.get_asset(b04.item_id, "B04_10m")
        a08 = geo.get_asset(b08.item_id, "B08_10m")
        self.assertEqual(a04["checksum"], b04.checksum)
        self.assertEqual(a08["checksum"], b08.checksum)
        self.assertEqual(a04["size"], b04.size_bytes)
        self.assertEqual(a08["size"], b08.size_bytes)
        self.assertTrue(str(a04["href"]).endswith("B04_10m.jp2"))
        self.assertTrue(str(a08["href"]).endswith("B08_10m.jp2"))
        self.assertTrue(geo.verify(b04.item_id))


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(
    os.environ.get("EO_GE_REAL_INGEST") == "1" and bool(os.environ.get("CDSE_TOKEN")),
    "EXTERNAL_INTEGRATION: requiere EO_GE_REAL_INGEST=1 y CDSE_TOKEN",
)
class TestRealIngestExternal(unittest.TestCase):
    """Descarga real de un asset. No forma parte de la suite offline."""

    def test_real_b04_ingest(self):
        from app.connectors.base import DiscoveryQuery

        root = ROOT
        store = LocalDataStore(root / "storage")
        catalog = Catalog(root / "catalog" / "catalog.sqlite")
        self.addCleanup(catalog.close)
        conn = Sentinel2L2AConnector()
        target = "S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402"
        refs = conn.discover(DiscoveryQuery(
            collection="sentinel-2-l2a",
            bbox=(-108.6, 25.4, -108.3, 25.7),
            datetime="2026-08-28T00:00:00Z/2026-08-29T00:00:00Z",
            limit=20,
        ))
        chosen = next((r for r in refs if r.source_id == target), None)
        if chosen is None:
            chosen = conn.select_item(refs)
        self.assertIsNotNone(chosen)
        result = ingest_sentinel2_asset(
            chosen,
            store,
            catalog,
            asset_name="B04_10m",
            connector=conn,
        )
        self.assertGreater(result.size_bytes, 0)
        self.assertEqual(len(result.checksum), 64)
        geo = GeoDataInterface(catalog, store)
        self.assertTrue(geo.verify(result.item_id))
        again = ingest_sentinel2_asset(chosen, store, catalog, asset_name="B04_10m", connector=conn)
        self.assertEqual(again.checksum, result.checksum)
        self.assertTrue(again.reused)


if __name__ == "__main__":
    unittest.main()
