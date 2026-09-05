"""Validador Sentinel-2 L2A (S-A.8).

Anade reglas especificas de Sentinel-2 sobre el validador base: plataforma,
instrumento, nivel de procesamiento, tile MGRS y coherencia CRS-tile.
"""

from __future__ import annotations

import re
from typing import Any

from app.validators.base import BaseValidator, ValidationResult

_TILE_RE = re.compile(r"^T\d{2}[A-Z]{3}$")
_S2_BANDS = {f"B{i:02d}" for i in range(1, 13)} | {"B8A"}


def _epsg_from_tile(tile: str | None) -> int | None:
    if not tile or not _TILE_RE.match(tile):
        return None
    zone, band = tile[1:3], tile[3]
    return (32600 if band >= "N" else 32700) + int(zone)


class Sentinel2Validator(BaseValidator):
    """Validador para Sentinel-2 L2A."""

    product = "SENTINEL2_L2A"

    def is_applicable(self, data: dict[str, Any]) -> bool:
        src = data.get("source", {})
        prod = data.get("product", {})
        mission = (src.get("mission") or "").lower()
        product = (prod.get("product") or "").upper()
        level = (prod.get("processing_level") or "").upper()
        return (
            "sentinel-2" in mission
            or "sentinel2" in mission
            or product.startswith("S2")
            or level in ("L2A", "L2")
        )

    def _product_checks(self, d: dict, r: ValidationResult) -> None:
        src = d.get("source", {})
        prod = d.get("product", {})
        sp = d.get("spatial", {})

        platform = (src.get("platform") or "").lower()
        if platform and not platform.startswith("sentinel-2"):
            self._err(r, "S2_PLATFORM_INVALID", "source.platform", f"plataforma no Sentinel-2: {platform}")

        instrument = (src.get("instrument") or "").lower()
        if instrument and instrument not in ("msi",):
            self._err(r, "S2_INSTRUMENT_INVALID", "source.instrument", f"instrumento no MSI: {instrument}")

        level = (prod.get("processing_level") or "").upper()
        if level and level not in ("L2A", "L2"):
            self._err(r, "S2_LEVEL_INVALID", "product.processing_level", f"nivel no L2A: {level}")

        tile = sp.get("tile")
        if tile and not _TILE_RE.match(str(tile)):
            self._err(r, "S2_TILE_INVALID", "spatial.tile", f"tile MGRS invalido: {tile}")

        epsg = sp.get("epsg")
        if tile and epsg is not None and _TILE_RE.match(str(tile)):
            derived = _epsg_from_tile(str(tile))
            if derived is not None and derived != epsg:
                self._err(r, "S2_CRS_TILE_MISMATCH", "spatial.epsg", f"epsg {epsg} no coincide con tile {tile} (esperado {derived})")

        bands = d.get("data", {}).get("raster", {}).get("bands", [])
        for b in bands:
            name = b.get("name")
            if name and name not in _S2_BANDS:
                self._warn(r, "S2_BAND_UNKNOWN", f"data.raster.bands.{name}", f"banda no estandar Sentinel-2: {name}")
