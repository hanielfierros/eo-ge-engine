"""Implementacion local (filesystem) del Data Store (S-A.9)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from app.normalizers.base import validate_against_contract
from app.storage.base import (
    DataStore,
    FileMetadata,
    StorageConflictError,
    StorageError,
    StorageNotFoundError,
    validate_id,
    validate_relative_path,
)

METADATA_FILENAME = "metadata.json"
MANIFEST_FILENAME = "manifest.json"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class LocalDataStore(DataStore):
    """Data Store local: filesystem + metadata JSON + SHA-256."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.source_cache = self.root / "source_cache"
        self.normalized = self.root / "normalized"
        self.derived = self.root / "derived"
        self.staging = self.root / ".staging"
        for d in (self.source_cache, self.normalized, self.derived, self.staging):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _product_dir(self, deterministic_id: str) -> Path:
        return self.normalized / validate_id(deterministic_id)

    def _staging_dir(self, deterministic_id: str) -> Path:
        return self.staging / validate_id(deterministic_id)

    def _manifest_path(self, deterministic_id: str) -> Path:
        return self._product_dir(deterministic_id) / MANIFEST_FILENAME

    def _load_manifest(self, deterministic_id: str) -> dict[str, Any]:
        p = self._manifest_path(deterministic_id)
        if not p.exists():
            return {"files": {}}
        return json.loads(p.read_text(encoding="utf-8"))

    def _save_manifest(self, deterministic_id: str, manifest: dict[str, Any]) -> None:
        _atomic_write_json(self._manifest_path(deterministic_id), manifest)

    # ------------------------------------------------------------------ #
    def exists(self, deterministic_id: str) -> bool:
        return self._product_dir(deterministic_id).exists()

    def put_metadata(self, deterministic_id: str, metadata: dict[str, Any]) -> None:
        validate_id(deterministic_id)
        errors = validate_against_contract(metadata)
        if errors:
            raise StorageError("metadata INVALID (no se persiste): " + "; ".join(errors))

        if self.exists(deterministic_id):
            existing = self.get_metadata(deterministic_id)
            if existing == metadata:
                return  # idempotente: mismo contenido
            raise StorageConflictError(f"producto ya existe con contenido distinto: {deterministic_id}")

        staging = self._staging_dir(deterministic_id)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            _atomic_write_json(staging / METADATA_FILENAME, metadata)
            _atomic_write_json(staging / MANIFEST_FILENAME, {"files": {}})
            final = self._product_dir(deterministic_id)
            os.replace(staging, final)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def get_metadata(self, deterministic_id: str) -> dict[str, Any] | None:
        p = self._product_dir(deterministic_id) / METADATA_FILENAME
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def delete(self, deterministic_id: str) -> None:
        p = self._product_dir(deterministic_id)
        if p.exists():
            shutil.rmtree(p)
        else:
            raise StorageNotFoundError(f"producto no encontrado: {deterministic_id}")

    # ------------------------------------------------------------------ #
    def put_file(self, deterministic_id: str, file_meta: FileMetadata, source_path: Path) -> FileMetadata:
        validate_id(deterministic_id)
        if not self.exists(deterministic_id):
            raise StorageNotFoundError(f"producto no encontrado: {deterministic_id}")
        rel = validate_relative_path(file_meta.relative_path)
        src = Path(source_path)
        if not src.is_file():
            raise StorageError(f"archivo fuente no existe: {src}")

        dest_dir = self._product_dir(deterministic_id) / "files"
        dest = dest_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        shutil.copy2(src, tmp)
        size = tmp.stat().st_size
        sha = _sha256_file(tmp)
        os.replace(tmp, dest)

        file_meta.relative_path = rel
        file_meta.filename = Path(rel).name
        file_meta.size = size
        file_meta.sha256 = sha

        manifest = self._load_manifest(deterministic_id)
        manifest.setdefault("files", {})[rel] = file_meta.to_dict()
        self._save_manifest(deterministic_id, manifest)
        return file_meta

    def get_file(self, deterministic_id: str, relative_path: str) -> Path | None:
        rel = validate_relative_path(relative_path)
        p = self._product_dir(deterministic_id) / "files" / rel
        return p if p.is_file() else None

    # ------------------------------------------------------------------ #
    def verify(self, deterministic_id: str) -> bool:
        p = self._product_dir(deterministic_id)
        if not p.exists():
            return False
        meta_path = p / METADATA_FILENAME
        if not meta_path.is_file():
            return False
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if validate_against_contract(metadata):
            return False

        manifest = self._load_manifest(deterministic_id)
        for rel, fm in manifest.get("files", {}).items():
            fpath = p / "files" / rel
            if not fpath.is_file():
                return False
            if fm.get("size") is not None and fpath.stat().st_size != fm["size"]:
                return False
            if fm.get("sha256") and _sha256_file(fpath) != fm["sha256"]:
                return False
        return True

    # ------------------------------------------------------------------ #
    def cleanup_staging(self) -> int:
        removed = 0
        if self.staging.exists():
            for d in self.staging.iterdir():
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        return removed

    def get_state(self, deterministic_id: str) -> str | None:
        if self._product_dir(deterministic_id).exists():
            return "COMMITTED"
        if self._staging_dir(deterministic_id).exists():
            return "STAGED"
        return None
