"""Base de normalizadores (S-A.7).

Un normalizador transforma una SourceRepresentation en un objeto compatible
con el contrato EO-GE NORMALIZED DATA CONTRACT V1.0. Aqui solo se valida la
estructura contra el JSON Schema; el validador cientifico es S-A.8.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.connectors.base import SourceRepresentation

CONTRACT_SCHEMA = Path(__file__).resolve().parent.parent.parent / "contracts" / "eo_ge_normalized_data.schema.json"

_format_checker = FormatChecker()


@_format_checker.checks("date-time")
def _is_datetime(value):
    if not isinstance(value, str):
        return False
    s = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


class NormalizationError(Exception):
    """Error de normalizacion (fuente incompatible o incompleta)."""


def load_contract_schema() -> dict[str, Any]:
    return json.loads(CONTRACT_SCHEMA.read_text(encoding="utf-8"))


def validate_against_contract(instance: dict[str, Any]) -> list[str]:
    """Valida la estructura contra el JSON Schema. Devuelve lista de errores."""
    validator = Draft202012Validator(load_contract_schema(), format_checker=_format_checker)
    return [e.message for e in sorted(validator.iter_errors(instance), key=lambda e: str(e.path))]


class BaseNormalizer:
    """Interfaz minima de normalizadores."""

    source: str = "unknown"
    product: str = "unknown"

    def normalize(self, sr: SourceRepresentation) -> dict[str, Any]:
        raise NotImplementedError

    def normalize_validated(self, sr: SourceRepresentation) -> dict[str, Any]:
        output = self.normalize(sr)
        errors = validate_against_contract(output)
        if errors:
            raise NormalizationError("salida no compatible con el contrato V1.0: " + "; ".join(errors))
        return output
