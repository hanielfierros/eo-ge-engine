"""Tests offline del conector Sentinel-2 L2A (S-A.6).

No dependen de CDSE: usan fixtures y mocks de requests. Cubren discovery,
seleccion, metadata, descarga (incluyendo errores), integridad, autenticacion
y SourceRepresentation.

    python -m unittest tests.test_sentinel2_connector -v
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.connectors.base import (
    AuthenticationError,
    DiscoveryError,
    DiscoveryQuery,
    DownloadedResource,
    IntegrityError,
    NotFoundError,
    RateLimitError,
    SourceReference,
    sha256_file,
)
from app.connectors.sentinel2 import (
    Sentinel2L2AConnector,
    UnsupportedAssetError,
    _normalize_tile,
    comparable_sha256,
    parse_official_checksum,
    resolve_official_https_href,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_item.json"


def _load_item() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _make_ref() -> SourceReference:
    item = _load_item()
    return SourceReference(source_id=item["id"], collection=item["collection"], item=item)


def _query() -> DiscoveryQuery:
    return DiscoveryQuery(
        collection="sentinel-2-l2a",
        bbox=(-109.0, 25.0, -108.0, 26.0),
        datetime="2026-08-01T00:00:00Z/2026-09-04T00:00:00Z",
        limit=5,
    )


class _FakeResponse:
    def __init__(self, status_code=200, body=None, json_body=None, headers=None, content=None):
        self.status_code = status_code
        self._body = body
        self._json = json_body
        self.headers = headers or {}
        self._content = content or b""

    def json(self):
        if self._json is not None:
            return self._json
        if self._body is not None:
            return json.loads(self._body)
        raise ValueError("no json")

    def iter_content(self, chunk_size=65536):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestDiscovery(unittest.TestCase):
    def test_discover_ok(self):
        conn = Sentinel2L2AConnector()
        fake = _FakeResponse(json_body={"features": [_load_item()]})
        with mock.patch.object(conn._session, "post", return_value=fake) as m:
            refs = conn.discover(_query())
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].source_id, "S2A_MSIL2A_20260901T174731_N0512_R098_T12RYP_20260902T051416")
        self.assertEqual(m.call_count, 1)

    def test_discover_empty(self):
        conn = Sentinel2L2AConnector()
        fake = _FakeResponse(json_body={"features": []})
        with mock.patch.object(conn._session, "post", return_value=fake):
            refs = conn.discover(_query())
        self.assertEqual(refs, [])

    def test_discover_malformed(self):
        conn = Sentinel2L2AConnector()
        fake = _FakeResponse(status_code=200, body="<html>not json</html>")
        with mock.patch.object(conn._session, "post", return_value=fake):
            with self.assertRaises(DiscoveryError):
                conn.discover(_query())

    def test_discover_429(self):
        conn = Sentinel2L2AConnector()
        fake = _FakeResponse(status_code=429)
        with mock.patch.object(conn._session, "post", return_value=fake):
            with self.assertRaises(RateLimitError):
                conn.discover(_query())


class TestSelection(unittest.TestCase):
    def test_select_lowest_cloud(self):
        conn = Sentinel2L2AConnector()
        a = _make_ref()
        b = _load_item()
        b["id"] = "S2B_..._T12RYP_..._cloudy"
        b["properties"]["eo:cloud_cover"] = 99.0
        refs = [a, SourceReference(source_id=b["id"], collection=b["collection"], item=b)]
        chosen = conn.select_item(refs)
        self.assertEqual(chosen.source_id, a.source_id)

    def test_select_empty(self):
        conn = Sentinel2L2AConnector()
        self.assertIsNone(conn.select_item([]))


class TestDownload(unittest.TestCase):
    def test_download_ok(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        content = b"fake jp2 data"
        fake = _FakeResponse(status_code=200, content=content, headers={"content-length": str(len(content))})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "B04_10m.jp2"
            with mock.patch.object(conn._session, "get", return_value=fake):
                res = conn.download(ref, dest, asset_name="B04_10m")
            self.assertEqual(res.size_bytes, len(content))
            self.assertTrue(dest.exists())

    def test_download_404(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        fake = _FakeResponse(status_code=404)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(NotFoundError):
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")

    def test_download_401(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        fake = _FakeResponse(status_code=401)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(AuthenticationError):
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")

    def test_download_429_retry_then_success(self):
        conn = Sentinel2L2AConnector(max_retries=2, backoff_seconds=0.0)
        ref = _make_ref()
        ok = _FakeResponse(status_code=200, content=b"ok")
        limited = _FakeResponse(status_code=429, headers={"retry-after": "0"})
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", side_effect=[limited, ok]) as m:
                res = conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")
            self.assertEqual(res.size_bytes, 2)
            self.assertEqual(m.call_count, 2)

    def test_download_500_retries_exhausted(self):
        conn = Sentinel2L2AConnector(max_retries=1, backoff_seconds=0.0)
        ref = _make_ref()
        fake = _FakeResponse(status_code=500)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(Exception):
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")

    def test_s3_asset_unsupported(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        ref.item["assets"]["B04_10m"]["href"] = "s3://eodata/Sentinel-2/.../B04.jp2"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnsupportedAssetError):
                conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")

    def test_s3_with_official_https_alternate(self):
        conn = Sentinel2L2AConnector(token="UNITTEST_PLACEHOLDER_TOKEN_VALUE")
        ref = _make_ref()
        official = "https://download.dataspace.copernicus.eu/odata/v1/Products(uuid)/Nodes(B04)/$value"
        ref.item["assets"]["B04_10m"]["href"] = "s3://eodata/Sentinel-2/B04.jp2"
        ref.item["assets"]["B04_10m"]["alternate"] = {
            "https": {"href": official, "auth:refs": ["oidc"]}
        }
        content = b"fake jp2 data"
        fake = _FakeResponse(status_code=200, content=content)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "B04_10m.jp2"
            with mock.patch.object(conn._session, "get", return_value=fake) as m:
                res = conn.download(ref, dest, asset_name="B04_10m")
            self.assertEqual(res.source_url, official)
            self.assertEqual(res.size_bytes, len(content))
            called_url = m.call_args.args[0]
            self.assertEqual(called_url, official)
            self.assertTrue(called_url.startswith("https://"))
            self.assertFalse(called_url.startswith("s3://"))

    def test_s3_without_alternate_rejected(self):
        asset = {"href": "s3://eodata/Sentinel-2/B04.jp2"}
        with self.assertRaises(UnsupportedAssetError):
            resolve_official_https_href(asset, "B04_10m")

    def test_invented_s3_https_not_used(self):
        asset = {"href": "s3://eodata/Sentinel-2/B04.jp2", "alternate": {"https": {"href": "ftp://not-official"}}}
        with self.assertRaises(UnsupportedAssetError):
            resolve_official_https_href(asset, "B04_10m")

    def test_download_403(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        fake = _FakeResponse(status_code=403)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(AuthenticationError):
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")

    def test_download_timeout(self):
        import requests
        conn = Sentinel2L2AConnector(max_retries=0, backoff_seconds=0.0)
        ref = _make_ref()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", side_effect=requests.exceptions.Timeout("t")):
                with self.assertRaises(Exception) as ctx:
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")
            self.assertIn("timeout", str(ctx.exception).lower())

    def test_download_empty_file(self):
        conn = Sentinel2L2AConnector(max_retries=0, backoff_seconds=0.0)
        ref = _make_ref()
        fake = _FakeResponse(status_code=200, content=b"")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(IntegrityError):
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")

    def test_download_content_length_mismatch(self):
        conn = Sentinel2L2AConnector(max_retries=0, backoff_seconds=0.0)
        ref = _make_ref()
        fake = _FakeResponse(status_code=200, content=b"abc", headers={"Content-Length": "99"})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.jp2"
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(IntegrityError):
                    conn.download(ref, dest, asset_name="B04_10m")
            self.assertFalse(dest.exists())

    def test_download_idempotent_same_sha(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        content = b"idempotent-bytes"
        fake = _FakeResponse(status_code=200, content=content)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "B04_10m.jp2"
            with mock.patch.object(conn._session, "get", return_value=fake) as m:
                a = conn.download(ref, dest, asset_name="B04_10m")
                b = conn.download(ref, dest, asset_name="B04_10m")
            self.assertEqual(m.call_count, 1)
            self.assertEqual(a.checksum, b.checksum)
            self.assertEqual(a.checksum, hashlib.sha256(content).hexdigest())

    def test_official_checksum_mismatch(self):
        conn = Sentinel2L2AConnector(max_retries=0)
        ref = _make_ref()
        ref.item["assets"]["B04_10m"]["file:checksum"] = "a" * 64
        fake = _FakeResponse(status_code=200, content=b"abc")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.jp2"
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(IntegrityError):
                    conn.download(ref, dest, asset_name="B04_10m")
            self.assertFalse(dest.exists())

    def test_official_sha3_256_match(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        content = b"sha3-payload"
        digest = hashlib.sha3_256(content).hexdigest()
        ref.item["assets"]["B04_10m"]["file:checksum"] = "1620" + digest
        fake = _FakeResponse(status_code=200, content=content)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.jp2"
            with mock.patch.object(conn._session, "get", return_value=fake):
                res = conn.download(ref, dest, asset_name="B04_10m")
            self.assertEqual(res.checksum_verification, "OFFICIAL_SHA3_256_MATCH")
            self.assertEqual(res.checksum, hashlib.sha256(content).hexdigest())

    def test_oidc_without_token_fails_fast(self):
        conn = Sentinel2L2AConnector(token=None)
        ref = _make_ref()
        ref.item["assets"]["B04_10m"]["href"] = "s3://eodata/Sentinel-2/B04.jp2"
        ref.item["assets"]["B04_10m"]["alternate"] = {
            "https": {
                "href": "https://download.dataspace.copernicus.eu/odata/v1/Products(uuid)/$value",
                "auth:refs": ["oidc"],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get") as m:
                with self.assertRaises(AuthenticationError):
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")
            m.assert_not_called()


class TestIntegrity(unittest.TestCase):
    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello")
            p = Path(f.name)
        self.assertEqual(sha256_file(p), hashlib.sha256(b"hello").hexdigest())
        p.unlink()

    def test_verify_ok(self):
        conn = Sentinel2L2AConnector()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"data")
            p = Path(f.name)
        res = DownloadedResource(path=p, checksum=hashlib.sha256(b"data").hexdigest())
        self.assertTrue(conn.verify(res))
        p.unlink()

    def test_verify_bad(self):
        conn = Sentinel2L2AConnector()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"data")
            p = Path(f.name)
        res = DownloadedResource(path=p, checksum="0" * 64)
        self.assertFalse(conn.verify(res))
        p.unlink()


class TestAuthenticationAndSecurity(unittest.TestCase):
    def test_token_absent(self):
        env = {k: v for k, v in os.environ.items() if k not in {"CDSE_TOKEN", "CDSE_ACCESS_TOKEN"}}
        with mock.patch.dict(os.environ, env, clear=True):
            conn = Sentinel2L2AConnector()
            self.assertIsNone(conn.token)

    def test_token_present_from_env(self):
        env = {k: v for k, v in os.environ.items() if k not in {"CDSE_TOKEN", "CDSE_ACCESS_TOKEN"}}
        env["CDSE_TOKEN"] = "UNITTEST_PLACEHOLDER_TOKEN_VALUE"
        with mock.patch.dict(os.environ, env, clear=True):
            conn = Sentinel2L2AConnector()
            self.assertEqual(conn.token, "UNITTEST_PLACEHOLDER_TOKEN_VALUE")

    def test_token_not_in_exception(self):
        secret = "UNITTEST_PLACEHOLDER_TOKEN_VALUE"
        conn = Sentinel2L2AConnector(token=secret)
        ref = _make_ref()
        fake = _FakeResponse(status_code=401)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(conn._session, "get", return_value=fake):
                with self.assertRaises(AuthenticationError) as ctx:
                    conn.download(ref, Path(tmp) / "x.jp2", asset_name="B04_10m")
            text = str(ctx.exception)
            self.assertNotIn(secret, text)

    def test_token_not_in_source_representation(self):
        secret = "UNITTEST_PLACEHOLDER_TOKEN_VALUE"
        conn = Sentinel2L2AConnector(token=secret)
        ref = _make_ref()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            p = Path(f.name)
        res = DownloadedResource(path=p, size_bytes=1, checksum="ab", asset_name="B04_10m", source_url="https://x")
        sr = conn.build_source_representation(ref, res)
        blob = json.dumps(sr.to_dict())
        self.assertNotIn(secret, blob)
        p.unlink()

    def test_comparable_sha256_only_when_unambiguous(self):
        self.assertEqual(comparable_sha256({"file:checksum": "a" * 64}), "a" * 64)
        self.assertIsNone(comparable_sha256({"file:checksum": "d41d8cd98f00b204e9800998ecf8427e"}))
        self.assertEqual(
            comparable_sha256({"checksum:multihash": "1220" + "ab" * 32}),
            "ab" * 32,
        )
        self.assertIsNone(comparable_sha256({"file:checksum": "1620" + "ab" * 32}))
        algo, digest = parse_official_checksum({"file:checksum": "1620" + "ab" * 32})
        self.assertEqual(algo, "sha3_256")
        self.assertEqual(digest, "ab" * 32)

    def test_mgrs_grid_code_normalized(self):
        self.assertEqual(_normalize_tile("MGRS-12RYP", "S2B_x_T12RYP_y"), "T12RYP")
        self.assertEqual(_normalize_tile("T12RYP", None), "T12RYP")


class TestSourceRepresentation(unittest.TestCase):
    def test_build_ok(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            p = Path(f.name)
        res = DownloadedResource(path=p, size_bytes=1, checksum=None, asset_name="B04_10m", source_url="https://x")
        sr = conn.build_source_representation(ref, res)
        d = sr.to_dict()
        self.assertEqual(d["source"], "COPERNICUS_DATA_SPACE")
        self.assertEqual(d["product"], "SENTINEL2_L2A")
        self.assertEqual(d["source_id"], ref.source_id)
        self.assertIn("tile", d["spatial"])
        self.assertIn("observation_time", d["acquisition"])
        p.unlink()

    def test_build_normalizes_mgrs_grid_code(self):
        conn = Sentinel2L2AConnector()
        ref = _make_ref()
        ref.item["properties"]["grid:code"] = "MGRS-12RYP"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            p = Path(f.name)
        res = DownloadedResource(path=p, size_bytes=1, checksum=None, asset_name="B04_10m", source_url="https://x")
        sr = conn.build_source_representation(ref, res)
        self.assertEqual(sr.spatial["tile"], "T12RYP")
        p.unlink()


if __name__ == "__main__":
    unittest.main()
