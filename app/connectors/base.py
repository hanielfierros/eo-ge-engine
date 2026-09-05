"""Base de conectores (S-A.5/S-A.6).

Define la interfaz comun (BaseConnector), el modelo de errores, el objeto
intermedio SourceRepresentation y las capabilities declaradas por conector.
El Connector entrega la fuente original; la normalizacion ocurre aguas abajo.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Errores (jerarquia)
# --------------------------------------------------------------------------- #
class ConnectorError(Exception):
    """Error base de conector."""
    transient = False


class DiscoveryError(ConnectorError):
    """Fallo en discovery/busqueda."""
    transient = True


class AuthenticationError(ConnectorError):
    """Fallo de autenticacion (401/403)."""


class RateLimitError(ConnectorError):
    """Limite de peticiones (429)."""
    transient = True


class DownloadError(ConnectorError):
    """Fallo transitorio de descarga (timeout/5xx)."""
    transient = True


class IntegrityError(ConnectorError):
    """Checksum/archivo invalido."""


class NotFoundError(ConnectorError):
    """Recurso no encontrado (404)."""


class MetadataError(ConnectorError):
    """Metadata malformada o incompleta."""


class UnsupportedProductError(ConnectorError):
    """Producto no soportado por el conector."""


# --------------------------------------------------------------------------- #
# Estructuras de datos
# --------------------------------------------------------------------------- #
@dataclass
class DiscoveryQuery:
    """Consulta de discovery comun."""
    collection: str
    bbox: tuple[float, float, float, float] | None = None
    datetime: str | None = None
    cloud_cover_max: float | None = None
    limit: int = 10
    ids: list[str] | None = None


@dataclass
class SourceReference:
    """Referencia a un item/fuente descubierto."""
    source_id: str
    collection: str
    item: dict[str, Any] = field(default_factory=dict)


@dataclass
class DownloadedResource:
    """Recurso descargado localmente."""
    path: Path
    size_bytes: int = 0
    checksum: str | None = None
    checksum_algo: str = "sha256"
    asset_name: str | None = None
    source_url: str | None = None
    checksum_verification: str | None = None  # OFFICIAL_SHA256_MATCH | SHA-256_LOCAL


@dataclass
class SourceRepresentation:
    """Representacion intermedia fuente-original (entre Connector y Normalizer)."""
    source: str
    product: str
    source_id: str
    source_metadata: dict[str, Any]
    acquisition: dict[str, Any]
    spatial: dict[str, Any]
    temporal: dict[str, Any]
    resource: dict[str, Any]
    checksum: str | None
    provenance: dict[str, Any]
    collection_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "product": self.product,
            "source_id": self.source_id,
            "source_metadata": self.source_metadata,
            "acquisition": self.acquisition,
            "spatial": self.spatial,
            "temporal": self.temporal,
            "resource": self.resource,
            "checksum": self.checksum,
            "provenance": self.provenance,
            "collection_metadata": self.collection_metadata,
        }


# Capacidades declarables por un conector.
CAPABILITY_DISCOVERY = "discovery"
CAPABILITY_SPATIAL_FILTER = "spatial_filter"
CAPABILITY_TEMPORAL_FILTER = "temporal_filter"
CAPABILITY_TILE_FILTER = "tile_filter"
CAPABILITY_METADATA = "metadata"
CAPABILITY_DOWNLOAD = "download"
CAPABILITY_STREAMING = "streaming"
CAPABILITY_AUTHENTICATION = "authentication"
CAPABILITY_RESUME = "resume"
CAPABILITY_CHECKSUM = "checksum"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Conector base
# --------------------------------------------------------------------------- #
class BaseConnector:
    """Interfaz comun de conectores (descubrir / metadata / descargar / verificar)."""

    source: str = "unknown"
    capabilities: set[str] = set()

    def discover(self, query: DiscoveryQuery) -> list[SourceReference]:
        raise NotImplementedError

    def get_metadata(self, ref: SourceReference) -> dict[str, Any]:
        raise NotImplementedError

    def download(self, ref: SourceReference, dest: Path, asset_name: str | None = None) -> DownloadedResource:
        raise NotImplementedError

    def verify(self, resource: DownloadedResource) -> bool:
        if resource.checksum is None:
            return True
        return sha256_file(resource.path) == resource.checksum

    def has(self, capability: str) -> bool:
        return capability in self.capabilities
