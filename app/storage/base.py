"""Base del Data Store (S-A.9).

Interfaz reutilizable de persistencia para productos normalizados (contrato
V1.0). El Data Store trabaja con el deterministic_id del producto, persiste la
metadata normalizada como JSON y archivos cientificos asociados, con SHA-256,
escritura atomica, estados de persistencia y path safety.

El backend (local filesystem) puede sustituirse sin tocar Connector/Normalizer/
Validator.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# deterministic_id seguro: solo alfanumericos, guion y subrayado (sin '/', '\', '..').
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class StorageError(Exception):
    """Error base de almacenamiento."""


class StorageConflictError(StorageError):
    """Conflicto de contenido para el mismo deterministic_id."""


class StorageNotFoundError(StorageError):
    """Producto no encontrado."""


class StorageIntegrityError(StorageError):
    """Fallo de integridad (checksum/tamano)."""


class StorageState:
    STAGED = "STAGED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


def validate_id(deterministic_id: str) -> str:
    if not _ID_RE.match(deterministic_id):
        raise StorageError(f"deterministic_id inseguro: {deterministic_id!r}")
    return deterministic_id


def validate_relative_path(relative_path: str) -> str:
    s = relative_path.replace("\\", "/")
    p = Path(s)
    if (
        not s
        or s.startswith("/")
        or ".." in p.parts
        or p.is_absolute()
        or re.match(r"^[A-Za-z]:", s)
    ):
        raise StorageError(f"ruta relativa insegura: {relative_path!r}")
    return s


@dataclass
class FileMetadata:
    """Metadata de un archivo asociado al producto."""

    filename: str
    relative_path: str
    media_type: str | None = None
    size: int = 0
    sha256: str | None = None
    role: str | None = None
    format: str | None = None
    source_generated: str = "source"  # "source" | "generated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "size": self.size,
            "sha256": self.sha256,
            "role": self.role,
            "format": self.format,
            "source_generated": self.source_generated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FileMetadata":
        return cls(
            filename=d.get("filename", ""),
            relative_path=d.get("relative_path", ""),
            media_type=d.get("media_type"),
            size=int(d.get("size", 0)),
            sha256=d.get("sha256"),
            role=d.get("role"),
            format=d.get("format"),
            source_generated=d.get("source_generated", "source"),
        )


class DataStore(ABC):
    """Interfaz minima de almacenamiento."""

    @abstractmethod
    def put_metadata(self, deterministic_id: str, metadata: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_metadata(self, deterministic_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, deterministic_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete(self, deterministic_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def put_file(self, deterministic_id: str, file_meta: FileMetadata, source_path: Path) -> FileMetadata:
        raise NotImplementedError

    @abstractmethod
    def get_file(self, deterministic_id: str, relative_path: str) -> Path | None:
        raise NotImplementedError

    @abstractmethod
    def verify(self, deterministic_id: str) -> bool:
        raise NotImplementedError
