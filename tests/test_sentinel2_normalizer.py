"""Tests offline del normalizador Sentinel-2 L2A (S-A.7).

No dependen de CDSE. Cubren el mapping, determinismo, conservacion cientifica,
rechazo de fuentes invalidas y validacion contra el contrato V1.0.

    python -m unittest tests.test_sentinel2_normalizer -v
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.connectors.base import SourceRepresentation
from app.normalizers.base import NormalizationError, validate_against_contract
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"


def _load_sr() -> SourceRepresentation:
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return SourceRepresentation(
        source=d["source"],
        product=d["product"],
        source_id=d["source_id"],
        source_metadata=d["source_metadata"],
        acquisition=d["acquisition"],
        spatial=d["spatial"],
        temporal=d["temporal"],
        resource=d["resource"],
        checksum=d["checksum"],
        provenance=d["provenance"],
        collection_metadata=d["collection_metadata"],
    )


class TestNormalizerMapping(unittest.TestCase):
    def setUp(self):
        self.norm = Sentinel2L2ANormalizer()
        self.sr = _load_sr()
        self.out = self.norm.normalize(self.sr)

    def test_identity_deterministic(self):
        self.assertEqual(
            self.out["identity"]["id"],
            "SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1",
        )

    def test_data_class(self):
        self.assertEqual(self.out["data_class"], "SCIENTIFIC_PRODUCT")

    def test_source(self):
        self.assertEqual(self.out["source"]["provider"], "ESA")
        self.assertEqual(self.out["source"]["platform"], "sentinel-2b")
        self.assertEqual(self.out["source"]["instrument"], "msi")

    def test_product(self):
        self.assertEqual(self.out["product"]["product"], "S2MSI2A")
        self.assertEqual(self.out["product"]["processing_level"], "L2A")

    def test_acquisition(self):
        self.assertEqual(self.out["acquisition"]["observation_time"], "2026-08-28T17:48:59.024000Z")

    def test_spatial_crs_derived(self):
        self.assertEqual(self.out["spatial"]["epsg"], 32612)
        self.assertEqual(self.out["spatial"]["crs"], "EPSG:32612")
        self.assertEqual(self.out["spatial"]["tile"], "T12RYP")

    def test_raster_bands(self):
        bands = self.out["data"]["raster"]["bands"]
        names = [b["name"] for b in bands]
        self.assertIn("B04", names)
        self.assertIn("B08", names)
        self.assertIn("B8A", names)
        b04 = next(b for b in bands if b["name"] == "B04")
        self.assertEqual(b04["dtype"], "uint16")
        self.assertEqual(b04["scale"], 0.0001)
        self.assertEqual(b04["nodata"], 0)
        self.assertEqual(b04["variable"], "red")

    def test_cloud_cover_preserved(self):
        self.assertEqual(
            self.out["quality"]["dataset_quality"]["cloud_cover_percent"], 20.24
        )

    def test_provenance_preserved(self):
        self.assertEqual(self.out["provenance"]["provider"], "ESA / Copernicus")
        self.assertEqual(self.out["provenance"]["original_product"], self.sr.source_id)
        self.assertEqual(self.out["provenance"]["checksum"], "sha256:abc123")

    def test_optional_absence(self):
        # product.version es None -> se poda (ausente), no null.
        self.assertNotIn("version", self.out["product"])

    def test_schema_valid(self):
        self.assertEqual(validate_against_contract(self.out), [])


class TestDeterminism(unittest.TestCase):
    def test_deterministic(self):
        norm = Sentinel2L2ANormalizer()
        a = norm.normalize(_load_sr())
        b = norm.normalize(_load_sr())
        self.assertEqual(a, b)


class TestRejection(unittest.TestCase):
    def setUp(self):
        self.norm = Sentinel2L2ANormalizer()

    def _mutate(self, **kwargs):
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        d.update(kwargs)
        return SourceRepresentation(
            source=d["source"], product=d["product"], source_id=d["source_id"],
            source_metadata=d["source_metadata"], acquisition=d["acquisition"],
            spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
            checksum=d["checksum"], provenance=d["provenance"],
            collection_metadata=d["collection_metadata"],
        )

    def test_wrong_product(self):
        sr = self._mutate(product="LANDSAT_C2")
        with self.assertRaises(NormalizationError):
            self.norm.normalize(sr)

    def test_missing_bands(self):
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        d["source_metadata"]["assets"] = {}
        sr = SourceRepresentation(
            source=d["source"], product=d["product"], source_id=d["source_id"],
            source_metadata=d["source_metadata"], acquisition=d["acquisition"],
            spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
            checksum=d["checksum"], provenance=d["provenance"],
            collection_metadata=d["collection_metadata"],
        )
        with self.assertRaises(NormalizationError):
            self.norm.normalize(sr)

    def test_band_without_dtype(self):
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        d["collection_metadata"]["B04_10m"].pop("data_type", None)
        sr = SourceRepresentation(
            source=d["source"], product=d["product"], source_id=d["source_id"],
            source_metadata=d["source_metadata"], acquisition=d["acquisition"],
            spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
            checksum=d["checksum"], provenance=d["provenance"],
            collection_metadata=d["collection_metadata"],
        )
        with self.assertRaises(NormalizationError):
            self.norm.normalize(sr)

    def test_missing_crs(self):
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        d["spatial"]["epsg"] = None
        d["spatial"]["tile"] = None
        d["source_metadata"]["properties"]["grid:code"] = None
        sr = SourceRepresentation(
            source=d["source"], product=d["product"], source_id=d["source_id"],
            source_metadata=d["source_metadata"], acquisition=d["acquisition"],
            spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
            checksum=d["checksum"], provenance=d["provenance"],
            collection_metadata=d["collection_metadata"],
        )
        with self.assertRaises(NormalizationError):
            self.norm.normalize(sr)

    def test_invalid_datetime_rejected_by_schema(self):
        sr = self._mutate()
        sr.acquisition["observation_time"] = "not-a-date"
        out = self.norm.normalize(sr)
        errors = validate_against_contract(out)
        self.assertTrue(errors)


class TestEndToEndOffline(unittest.TestCase):
    def test_connector_to_normalizer(self):
        # Emula el flujo: SourceRepresentation (fixture) -> normalizador -> contrato.
        norm = Sentinel2L2ANormalizer()
        sr = _load_sr()
        out = norm.normalize_validated(sr)
        self.assertEqual(out["contract"]["version"], "1.0")
        self.assertEqual(out["data"]["kind"], "raster")
        self.assertEqual(validate_against_contract(out), [])


if __name__ == "__main__":
    unittest.main()
