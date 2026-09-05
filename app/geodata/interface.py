"""GeoData Interface (S-A.11).

Fachada interna y read-oriented sobre Catalog + DataStore. Coordina y resuelve
referencias; no normaliza, no valida, no descarga, no reproyecta ni calcula
indices. Delegada la busqueda al Catalog y la integridad al Data Store.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.catalog.catalog import Catalog
from app.storage.base import DataStore


class GeoDataError(Exception):
    """Error base de la interfaz geoespacial."""


class ItemNotFoundError(GeoDataError):
    """Item (deterministic_id) no encontrado en el Catalog."""


class AssetNotFoundError(GeoDataError):
    """Asset no encontrado en el Item."""


class MetadataNotFoundError(GeoDataError):
    """Metadata no encontrada en el Data Store."""


class StorageReferenceError(GeoDataError):
    """Referencia de archivo no resoluble en el Data Store."""


class GeoDataInterface:
    """Fachada de consulta sobre Catalog + Data Store."""

    def __init__(self, catalog: Catalog, data_store: DataStore) -> None:
        self.catalog = catalog
        self.store = data_store

    # ------------------------------------------------------------------ #
    def search(
        self,
        collection: str | None = None,
        datetime: str | None = None,
        datetime_start: str | None = None,
        datetime_end: str | None = None,
        platform: str | None = None,
        product: str | None = None,
        validation_status: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> list[dict[str, Any]]:
        return self.catalog.search(
            collection=collection,
            datetime_=datetime,
            datetime_start=datetime_start,
            datetime_end=datetime_end,
            platform=platform,
            product=product,
            validation_status=validation_status,
            bbox=bbox,
        )

    def get_item(self, deterministic_id: str) -> dict[str, Any]:
        item = self.catalog.get_item(deterministic_id)
        if item is None:
            raise ItemNotFoundError(f"item no encontrado: {deterministic_id}")
        return item

    def get_metadata(self, deterministic_id: str) -> dict[str, Any]:
        metadata = self.store.get_metadata(deterministic_id)
        if metadata is None:
            raise MetadataNotFoundError(f"metadata no encontrada: {deterministic_id}")
        return metadata

    def get_asset(self, deterministic_id: str, asset_key: str) -> dict[str, Any]:
        item = self.get_item(deterministic_id)
        for asset in item.get("assets", []):
            if asset.get("asset_key") == asset_key:
                return asset
        raise AssetNotFoundError(f"asset {asset_key!r} no encontrado en {deterministic_id}")

    def get_file(self, deterministic_id: str, relative_path: str) -> Path:
        path = self.store.get_file(deterministic_id, relative_path)
        if path is None:
            raise StorageReferenceError(f"archivo no resoluble: {deterministic_id}/{relative_path}")
        return path

    def exists(self, deterministic_id: str) -> bool:
        return self.store.exists(deterministic_id)

    def verify(self, deterministic_id: str) -> bool:
        return self.store.verify(deterministic_id)
