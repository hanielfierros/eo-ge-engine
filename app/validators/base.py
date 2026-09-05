"""Base del validador (S-A.8).

Valida un objeto normalizado (contrato V1.0) en dos niveles:
  A. Contrato (JSON Schema).
  B. Cientifico/semantico (reglas que el schema no puede garantizar).

El validador es una operacion pura: no modifica la entrada, no corrige datos,
no inventa metadata. Devuelve AVAILABLE / PARTIAL / INVALID.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.normalizers.base import validate_against_contract

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_CRS_RE = re.compile(r"^(EPSG|epsg):\d{4,6}$")


@dataclass
class ValidationResult:
    """Resultado estructurado y serializable de la validacion."""

    status: str = "AVAILABLE"
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
            "summary": self.summary,
        }


def _iso_datetime(value: str | None) -> datetime | None:
    if not value or not _ISO_RE.match(value):
        return None
    s = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class BaseValidator:
    """Validador base de datos normalizados (generic + hook por producto)."""

    product: str = "GENERIC"

    def is_applicable(self, data: dict[str, Any]) -> bool:
        return True

    def validate(self, data: dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        # --- Nivel A: contrato (JSON Schema) ---
        schema_errors = validate_against_contract(data)
        if schema_errors:
            for msg in schema_errors:
                result.errors.append({
                    "code": "SCHEMA_INVALID",
                    "field": None,
                    "message": msg,
                    "severity": "ERROR",
                })
            result.checks.append({"check": "contract_schema", "result": "FAIL"})
            result.status = "INVALID"
            result.summary = {"errors": len(result.errors), "warnings": 0}
            return result
        result.checks.append({"check": "contract_schema", "result": "PASS"})

        # --- Nivel B: semantico ---
        self._check_identity(data, result)
        self._check_temporal(data, result)
        self._check_spatial(data, result)
        self._check_raster(data, result)
        self._check_quality(data, result)
        self._check_provenance(data, result)
        self._product_checks(data, result)  # hook por producto

        result.status = self._derive_status(result)
        result.summary = {"errors": len(result.errors), "warnings": len(result.warnings)}
        return result

    # ------------------------------------------------------------------ #
    def _derive_status(self, result: ValidationResult) -> str:
        if result.errors:
            return "INVALID"
        if result.warnings:
            return "PARTIAL"
        return "AVAILABLE"

    def _err(self, result: ValidationResult, code: str, field: str, message: str) -> None:
        result.errors.append({"code": code, "field": field, "message": message, "severity": "ERROR"})
        result.checks.append({"check": code, "result": "FAIL"})

    def _warn(self, result: ValidationResult, code: str, field: str, message: str) -> None:
        result.warnings.append({"code": code, "field": field, "message": message, "severity": "WARNING"})
        result.checks.append({"check": code, "result": "WARN"})

    def _pass(self, result: ValidationResult, code: str) -> None:
        result.checks.append({"check": code, "result": "PASS"})

    # ------------------------------------------------------------------ #
    # Reglas semanticas genericas
    # ------------------------------------------------------------------ #
    def _check_identity(self, d: dict, r: ValidationResult) -> None:
        ident = d.get("identity", {})
        if not ident.get("id"):
            self._err(r, "IDENTITY_MISSING", "identity.id", "identidad ausente")
        else:
            self._pass(r, "IDENTITY_PRESENT")

    def _check_temporal(self, d: dict, r: ValidationResult) -> None:
        acq = d.get("acquisition", {})
        start = acq.get("start_time")
        end = acq.get("end_time")
        obs = acq.get("observation_time")
        if obs and _iso_datetime(obs) is None:
            self._err(r, "DATETIME_INVALID", "acquisition.observation_time", f"datetime invalido: {obs}")
        else:
            self._pass(r, "DATETIME_VALID")
        if start and end:
            s = _iso_datetime(start)
            e = _iso_datetime(end)
            if s and e and s > e:
                self._err(r, "TEMPORAL_INCONSISTENT", "acquisition", "start_time > end_time")
            else:
                self._pass(r, "TEMPORAL_ORDER")

    def _check_spatial(self, d: dict, r: ValidationResult) -> None:
        sp = d.get("spatial", {})
        crs = sp.get("crs")
        epsg = sp.get("epsg")
        if crs and not _CRS_RE.match(str(crs)):
            self._err(r, "CRS_INVALID", "spatial.crs", f"CRS invalido: {crs}")
        else:
            self._pass(r, "CRS_VALID")
        if epsg is not None and (not isinstance(epsg, int) or epsg < 1000 or epsg > 40000):
            self._err(r, "CRS_INVALID", "spatial.epsg", f"EPSG invalido: {epsg}")

        bbox = sp.get("bounds")
        if bbox is not None:
            if len(bbox) not in (4, 6) or not all(isinstance(v, (int, float)) for v in bbox):
                self._err(r, "BBOX_INVALID", "spatial.bounds", f"bbox invalido: {bbox}")
            elif len(bbox) >= 4 and bbox[0] >= bbox[2]:
                self._err(r, "BBOX_INVALID", "spatial.bounds", "oeste >= este")
            elif len(bbox) >= 4 and bbox[1] >= bbox[3]:
                self._err(r, "BBOX_INVALID", "spatial.bounds", "sur >= norte")
            else:
                self._pass(r, "BBOX_VALID")
        else:
            self._err(r, "BBOX_INVALID", "spatial.bounds", "bounds ausente")

        res = sp.get("resolution")
        if res is not None:
            x, y = res.get("x"), res.get("y")
            if x is not None and x <= 0:
                self._err(r, "RESOLUTION_INVALID", "spatial.resolution.x", f"resolucion no positiva: {x}")
            elif y is not None and y <= 0:
                self._err(r, "RESOLUTION_INVALID", "spatial.resolution.y", f"resolucion no positiva: {y}")

    def _check_raster(self, d: dict, r: ValidationResult) -> None:
        data = d.get("data", {})
        if data.get("kind") != "raster":
            self._err(r, "KIND_INVALID", "data.kind", f"se esperaba raster, se obtuvo {data.get('kind')}")
            return
        raster = data.get("raster", {})
        bands = raster.get("bands", [])
        if not bands:
            self._err(r, "BAND_STRUCTURE_INVALID", "data.raster.bands", "sin bandas")
            return
        self._pass(r, "BANDS_PRESENT")
        for b in bands:
            name = b.get("name")
            if not name:
                self._err(r, "BAND_STRUCTURE_INVALID", "data.raster.bands", "banda sin nombre")
            if b.get("units") == "":
                self._warn(r, "UNITS_MISSING", f"data.raster.bands.{name}", f"unidades vacias en banda {name}")

    def _check_quality(self, d: dict, r: ValidationResult) -> None:
        q = d.get("quality", {})
        cc = None
        dq = q.get("dataset_quality") or {}
        if "cloud_cover_percent" in dq:
            cc = dq["cloud_cover_percent"]
        if cc is not None:
            if cc < 0 or cc > 100:
                self._err(r, "CLOUD_COVER_OUT_OF_RANGE", "quality.dataset_quality.cloud_cover_percent", f"cloud cover fuera de rango: {cc}")
            else:
                self._pass(r, "CLOUD_COVER_VALID")

    def _check_provenance(self, d: dict, r: ValidationResult) -> None:
        prov = d.get("provenance", {})
        if not prov.get("provider"):
            self._err(r, "PROVENANCE_INCOMPLETE", "provenance.provider", "provider ausente")
        else:
            self._pass(r, "PROVENANCE_PROVIDER")
        if not prov.get("original_product"):
            self._err(r, "PROVENANCE_INCOMPLETE", "provenance.original_product", "producto original ausente")
        if prov.get("checksum") is None:
            self._warn(r, "CHECKSUM_MISSING", "provenance.checksum", "checksum no disponible")

    def _product_checks(self, d: dict, r: ValidationResult) -> None:
        """Hook: reglas especificas de producto. Base no hace nada."""
        return
