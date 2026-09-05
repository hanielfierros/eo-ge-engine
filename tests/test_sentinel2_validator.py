"""Tests del validador (S-A.8).

Cubren: AVAILABLE/PARTIAL/INVALID, reglas semanticas, reglas Sentinel-2,
inmutabilidad del input, determinismo y ataques.

    python -m unittest tests.test_sentinel2_validator -v
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from app.connectors.base import SourceRepresentation
from app.normalizers.sentinel2 import Sentinel2L2ANormalizer
from app.validators.sentinel2 import Sentinel2Validator

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sentinel2_source_representation.json"


def _valid_normalized() -> dict:
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sr = SourceRepresentation(
        source=d["source"], product=d["product"], source_id=d["source_id"],
        source_metadata=d["source_metadata"], acquisition=d["acquisition"],
        spatial=d["spatial"], temporal=d["temporal"], resource=d["resource"],
        checksum=d["checksum"], provenance=d["provenance"],
        collection_metadata=d["collection_metadata"],
    )
    return Sentinel2L2ANormalizer().normalize(sr)


class TestValidatorOutcomes(unittest.TestCase):
    def setUp(self):
        self.validator = Sentinel2Validator()

    def test_valid_available(self):
        r = self.validator.validate(_valid_normalized())
        self.assertEqual(r.status, "AVAILABLE")

    def test_contract_invalid(self):
        d = _valid_normalized()
        del d["identity"]
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")
        self.assertTrue(any(e["code"] == "SCHEMA_INVALID" for e in r.errors))

    def test_datetime_invalid(self):
        d = _valid_normalized()
        d["acquisition"]["observation_time"] = "not-a-date"
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")

    def test_crs_invalid(self):
        d = _valid_normalized()
        d["spatial"]["crs"] = "INVALID_CRS"
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")
        self.assertTrue(any(e["code"] == "CRS_INVALID" for e in r.errors))

    def test_resolution_invalid(self):
        d = _valid_normalized()
        d["spatial"]["resolution"] = {"x": -10.0, "y": -10.0, "unit": "m"}
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")

    def test_cloud_cover_high(self):
        d = _valid_normalized()
        d["quality"]["dataset_quality"]["cloud_cover_percent"] = 150.0
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")

    def test_cloud_cover_negative(self):
        d = _valid_normalized()
        d["quality"]["dataset_quality"]["cloud_cover_percent"] = -5.0
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")

    def test_identity_missing(self):
        d = _valid_normalized()
        d["identity"]["id"] = ""
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")

    def test_bbox_inconsistent(self):
        d = _valid_normalized()
        d["spatial"]["bounds"] = [-108.0, 25.0, -109.0, 26.0]  # oeste > este
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")

    def test_optional_metadata_absent_not_invalid(self):
        d = _valid_normalized()
        d["spatial"].pop("resolution", None)
        d["spatial"].pop("footprint", None)
        r = self.validator.validate(d)
        self.assertNotEqual(r.status, "INVALID")

    def test_checksum_absent_partial(self):
        d = _valid_normalized()
        d["provenance"].pop("checksum", None)
        d["data"]["storage"].pop("checksum", None)
        r = self.validator.validate(d)
        self.assertEqual(r.status, "PARTIAL")
        self.assertTrue(any(w["code"] == "CHECKSUM_MISSING" for w in r.warnings))

    def test_provenance_incomplete(self):
        d = _valid_normalized()
        d["provenance"]["provider"] = None
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")

    def test_sentinel2_valid(self):
        r = self.validator.validate(_valid_normalized())
        self.assertEqual(r.status, "AVAILABLE")

    def test_sentinel2_partial(self):
        d = _valid_normalized()
        d["provenance"].pop("checksum", None)
        r = self.validator.validate(d)
        self.assertEqual(r.status, "PARTIAL")


class TestSentinel2Rules(unittest.TestCase):
    def setUp(self):
        self.validator = Sentinel2Validator()

    def test_applicable(self):
        self.assertTrue(self.validator.is_applicable(_valid_normalized()))

    def test_wrong_platform(self):
        d = _valid_normalized()
        d["source"]["platform"] = "landsat-8"
        r = self.validator.validate(d)
        self.assertEqual(r.status, "INVALID")
        self.assertTrue(any(e["code"] == "S2_PLATFORM_INVALID" for e in r.errors))

    def test_wrong_instrument(self):
        d = _valid_normalized()
        d["source"]["instrument"] = "OLI"
        r = self.validator.validate(d)
        self.assertIn("S2_INSTRUMENT_INVALID", [e["code"] for e in r.errors])

    def test_wrong_level(self):
        d = _valid_normalized()
        d["product"]["processing_level"] = "L1C"
        r = self.validator.validate(d)
        self.assertIn("S2_LEVEL_INVALID", [e["code"] for e in r.errors])

    def test_crs_tile_mismatch(self):
        d = _valid_normalized()
        d["spatial"]["epsg"] = 32613  # tile T12RYP -> 32612
        d["spatial"]["crs"] = "EPSG:32613"
        r = self.validator.validate(d)
        self.assertIn("S2_CRS_TILE_MISMATCH", [e["code"] for e in r.errors])


class TestImmutabilityAndDeterminism(unittest.TestCase):
    def setUp(self):
        self.validator = Sentinel2Validator()

    def test_input_not_modified(self):
        d = _valid_normalized()
        before = copy.deepcopy(d)
        self.validator.validate(d)
        self.assertEqual(d, before)

    def test_deterministic(self):
        d = _valid_normalized()
        a = self.validator.validate(d).to_dict()
        b = self.validator.validate(copy.deepcopy(d)).to_dict()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
