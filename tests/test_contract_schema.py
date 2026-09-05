"""Tests de validacion del contrato normalizado EO-GE V1.0.

Validan el JSON Schema del contrato (no conectores). Ejecutar con:

    python -m unittest tests.test_contract_schema -v
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "contracts" / "eo_ge_normalized_data.schema.json"
EXAMPLES_DIR = ROOT / "contracts" / "examples"

VALID_EXAMPLES = [
    "sentinel2_l2a.json",
    "sentinel1_grd.json",
    "landsat_c2l2.json",
    "era5_land.json",
    "inegi_vector.json",
]


# jsonschema 4.x no registra "date-time" por defecto; se registra un checker.
_format_checker = FormatChecker()


@_format_checker.checks("date-time")
def _is_datetime(value):
    if not isinstance(value, str):
        return False
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


class TestContractSchemaValidExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load_schema()
        cls.validator = Draft202012Validator(cls.schema, format_checker=_format_checker)

    def _validate_ok(self, instance):
        errors = sorted(self.validator.iter_errors(instance), key=lambda e: str(e.path))
        self.assertEqual(errors, [], msg="\n".join(e.message for e in errors))

    def test_sentinel2_valid(self):
        self._validate_ok(_load_example("sentinel2_l2a.json"))

    def test_sentinel1_valid(self):
        self._validate_ok(_load_example("sentinel1_grd.json"))

    def test_landsat_valid(self):
        self._validate_ok(_load_example("landsat_c2l2.json"))

    def test_era5_land_valid(self):
        self._validate_ok(_load_example("era5_land.json"))

    def test_vector_valid(self):
        self._validate_ok(_load_example("inegi_vector.json"))


class TestContractSchemaInvalidCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load_schema()
        cls.validator = Draft202012Validator(cls.schema, format_checker=_format_checker)

    def _assert_invalid(self, instance, keyword_hint=None):
        errors = list(self.validator.iter_errors(instance))
        self.assertTrue(errors, "se esperaba que la instancia fuera invalida")
        if keyword_hint:
            self.assertTrue(
                any(keyword_hint in e.message or any(keyword_hint in p for p in e.path) for e in errors),
                f"no se encontro el problema esperado '{keyword_hint}'; errores: {[e.message for e in errors]}",
            )

    def test_missing_identity(self):
        inst = _load_example("sentinel2_l2a.json")
        del inst["identity"]
        self._assert_invalid(inst, "identity")

    def test_missing_crs(self):
        inst = _load_example("sentinel2_l2a.json")
        del inst["spatial"]["crs"]
        self._assert_invalid(inst, "crs")

    def test_invalid_quality(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["quality"]["status"] = "BOGUS"
        self._assert_invalid(inst)

    def test_invalid_timestamp(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["acquisition"]["start_time"] = "not-a-date"
        self._assert_invalid(inst)

    def test_invalid_dtype(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["data"]["raster"]["bands"][0]["dtype"] = "complex128"
        self._assert_invalid(inst)

    def test_incomplete_structure_missing_product(self):
        inst = _load_example("sentinel2_l2a.json")
        del inst["product"]
        self._assert_invalid(inst, "product")

    def test_invalid_data_class(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["data_class"] = "IMAGE"
        self._assert_invalid(inst)

    def test_raster_missing_kind_body(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["data"]["kind"] = "raster"
        del inst["data"]["raster"]
        self._assert_invalid(inst)

    def test_wrong_contract_version(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["contract"]["version"] = "2.0"
        self._assert_invalid(inst)


class TestContractSchemaMoreAttacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load_schema()
        cls.validator = Draft202012Validator(cls.schema, format_checker=_format_checker)

    def _assert_invalid(self, instance):
        errors = list(self.validator.iter_errors(instance))
        self.assertTrue(errors, "se esperaba que la instancia fuera invalida")

    def test_vector_missing_geometry_type(self):
        inst = _load_example("inegi_vector.json")
        del inst["data"]["vector"]["geometry_type"]
        self._assert_invalid(inst)

    def test_multidimensional_missing_dimensions(self):
        inst = _load_example("era5_land.json")
        del inst["data"]["multidimensional"]["dimensions"]
        self._assert_invalid(inst)

    def test_empty_identity(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["identity"]["id"] = ""
        self._assert_invalid(inst)

    def test_bounds_wrong_count(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["spatial"]["bounds"] = [1.0, 2.0, 3.0]
        self._assert_invalid(inst)

    def test_spatial_missing_bounds(self):
        inst = _load_example("sentinel2_l2a.json")
        del inst["spatial"]["bounds"]
        self._assert_invalid(inst)

    def test_acquisition_missing_start_time(self):
        inst = _load_example("sentinel2_l2a.json")
        del inst["acquisition"]["start_time"]
        self._assert_invalid(inst)

    def test_provenance_missing_provider(self):
        inst = _load_example("sentinel2_l2a.json")
        del inst["provenance"]["provider"]
        self._assert_invalid(inst)

    def test_band_missing_dtype(self):
        inst = _load_example("sentinel2_l2a.json")
        del inst["data"]["raster"]["bands"][0]["dtype"]
        self._assert_invalid(inst)

    def test_unexpected_top_level_property(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["unexpected_field"] = True
        self._assert_invalid(inst)

    def test_kind_mismatch_raster_with_vector_body(self):
        inst = _load_example("sentinel2_l2a.json")
        inst["data"]["kind"] = "vector"
        del inst["data"]["raster"]
        # vector body ausente -> invalido
        self._assert_invalid(inst)


if __name__ == "__main__":
    unittest.main()
