"""Catalogo SQLite (modelo STAC-compatible) para el EO-GE ENGINE (S-A.10).

El Catalog indexa y permite descubrir los productos normalizados; el Data Store
conserva los datos. Usa `deterministic_id` como identidad primaria del Item.
No almacena arrays raster ni datos cientificos grandes.

Preparado para migrar posteriormente a PostgreSQL/PostGIS/STAC API.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_PATH_RE = re.compile(r"^(?!.*(?:^|/)\.\.(?:/|$)).*$")


class CatalogError(Exception):
    """Error base de catalogo."""


class CatalogIdConflictError(CatalogError):
    """Conflicto de contenido para el mismo deterministic_id."""


class CatalogPathError(CatalogError):
    """Ruta/href insegura."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_safe_path(value: str) -> str:
    s = value.replace("\\", "/")
    if (
        not s
        or s.startswith("/")
        or ".." in Path(s).parts
        or re.match(r"^[A-Za-z]:", s)
    ):
        raise CatalogPathError(f"ruta/href insegura: {value!r}")
    return s


_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    platform TEXT,
    product TEXT,
    version TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    source_id TEXT,
    product TEXT,
    platform TEXT,
    instrument TEXT,
    processing_level TEXT,
    datetime TEXT,
    start_datetime TEXT,
    end_datetime TEXT,
    geometry TEXT,
    bbox TEXT,
    cloud_cover REAL,
    validation_status TEXT,
    storage_path TEXT,
    properties TEXT,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (collection_id) REFERENCES collections(id)
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    asset_key TEXT,
    href TEXT,
    media_type TEXT,
    role TEXT,
    title TEXT,
    size INTEGER,
    checksum TEXT,
    format TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);
CREATE INDEX IF NOT EXISTS idx_items_collection ON items(collection_id);
CREATE INDEX IF NOT EXISTS idx_items_datetime ON items(datetime);
CREATE INDEX IF NOT EXISTS idx_items_platform ON items(platform);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(validation_status);
CREATE INDEX IF NOT EXISTS idx_assets_item ON assets(item_id);
"""


class Catalog:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Collections
    # ------------------------------------------------------------------ #
    def register_collection(self, collection: dict[str, Any]) -> str:
        cid = collection["id"]
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO collections (id, title, description, platform, product, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, description=excluded.description,
                platform=excluded.platform, product=excluded.product,
                version=excluded.version, updated_at=excluded.updated_at
            """,
            (
                cid, collection.get("title"), collection.get("description"),
                collection.get("platform"), collection.get("product"),
                collection.get("version"), now, now,
            ),
        )
        self._conn.commit()
        return cid

    # ------------------------------------------------------------------ #
    # Items + Assets (transaccional)
    # ------------------------------------------------------------------ #
    def register_item(self, item: dict[str, Any]) -> str:
        item_id = item["id"]
        if not item_id:
            raise CatalogError("item sin id")

        existing = self.get_item(item_id)
        if existing is not None:
            if self._same_essential(existing, item):
                return item_id  # idempotente
            raise CatalogIdConflictError(f"item con id {item_id!r} ya existe con contenido distinto")

        collection_id = item.get("collection_id")
        if collection_id is None:
            raise CatalogError("item sin collection_id")

        if item.get("storage_path"):
            validate_safe_path(str(item["storage_path"]))

        now = _now_iso()
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                """
                INSERT INTO items (
                    id, collection_id, source_id, product, platform, instrument,
                    processing_level, datetime, start_datetime, end_datetime,
                    geometry, bbox, cloud_cover, validation_status, storage_path,
                    properties, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id, collection_id, item.get("source_id"), item.get("product"),
                    item.get("platform"), item.get("instrument"), item.get("processing_level"),
                    item.get("datetime"), item.get("start_datetime"), item.get("end_datetime"),
                    _json(item.get("geometry")), _json(item.get("bbox")),
                    item.get("cloud_cover"), item.get("validation_status"),
                    item.get("storage_path"), _json(item.get("properties")), now, now,
                ),
            )
            for a in item.get("assets", []):
                href = a.get("href")
                if href:
                    validate_safe_path(str(href))
                self._conn.execute(
                    """
                    INSERT INTO assets (item_id, asset_key, href, media_type, role, title, size, checksum, format)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id, a.get("asset_key"), href, a.get("media_type"),
                        a.get("role"), a.get("title"), a.get("size"),
                        a.get("checksum"), a.get("format"),
                    ),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return item_id

    def register_asset(self, item_id: str, asset: dict[str, Any]) -> None:
        if not self.exists(item_id):
            raise CatalogError(f"item no encontrado: {item_id}")
        href = asset.get("href")
        if href:
            validate_safe_path(str(href))
        self._conn.execute(
            """
            INSERT INTO assets (item_id, asset_key, href, media_type, role, title, size, checksum, format)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id, asset.get("asset_key"), href, asset.get("media_type"),
                asset.get("role"), asset.get("title"), asset.get("size"),
                asset.get("checksum"), asset.get("format"),
            ),
        )
        self._conn.commit()

    def _same_essential(self, existing: dict[str, Any], item: dict[str, Any]) -> bool:
        for key in ("collection_id", "source_id", "datetime"):
            if existing.get(key) != item.get(key):
                return False
        return True

    # ------------------------------------------------------------------ #
    # Lectura
    # ------------------------------------------------------------------ #
    def exists(self, item_id: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,))
        return cur.fetchone() is not None

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        item = self._row_to_item(row)
        item["assets"] = self._get_assets(item_id)
        return item

    def _get_assets(self, item_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM assets WHERE item_id = ?", (item_id,))
        return [
            {
                "asset_key": r["asset_key"], "href": r["href"], "media_type": r["media_type"],
                "role": r["role"], "title": r["title"], "size": r["size"],
                "checksum": r["checksum"], "format": r["format"],
            }
            for r in cur.fetchall()
        ]

    def _row_to_item(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "collection_id": row["collection_id"], "source_id": row["source_id"],
            "product": row["product"], "platform": row["platform"], "instrument": row["instrument"],
            "processing_level": row["processing_level"], "datetime": row["datetime"],
            "start_datetime": row["start_datetime"], "end_datetime": row["end_datetime"],
            "geometry": _unjson(row["geometry"]), "bbox": _unjson(row["bbox"]),
            "cloud_cover": row["cloud_cover"], "validation_status": row["validation_status"],
            "storage_path": row["storage_path"], "properties": _unjson(row["properties"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def remove_item(self, item_id: str) -> None:
        if not self.exists(item_id):
            raise CatalogError(f"item no encontrado: {item_id}")
        try:
            self._conn.execute("BEGIN")
            self._conn.execute("DELETE FROM assets WHERE item_id = ?", (item_id,))
            self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------ #
    # Busqueda
    # ------------------------------------------------------------------ #
    def search(
        self,
        collection: str | None = None,
        datetime_: str | None = None,
        datetime_start: str | None = None,
        datetime_end: str | None = None,
        platform: str | None = None,
        product: str | None = None,
        validation_status: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if collection:
            where.append("collection_id = ?")
            params.append(collection)
        if datetime_:
            where.append("datetime = ?")
            params.append(datetime_)
        if datetime_start:
            where.append("datetime >= ?")
            params.append(datetime_start)
        if datetime_end:
            where.append("datetime <= ?")
            params.append(datetime_end)
        if platform:
            where.append("platform = ?")
            params.append(platform)
        if product:
            where.append("product = ?")
            params.append(product)
        if validation_status:
            where.append("validation_status = ?")
            params.append(validation_status)

        sql = "SELECT * FROM items" + (" WHERE " + " AND ".join(where) if where else "")
        rows = self._conn.execute(sql, params).fetchall()
        items = [self._row_to_item(r) for r in rows]

        if bbox is not None:
            items = [i for i in items if self._bbox_intersects(i.get("bbox"), bbox)]

        for item in items:
            item["assets"] = self._get_assets(item["id"])
        return items

    def _bbox_intersects(self, stored: Any, query: tuple[float, float, float, float]) -> bool:
        if not stored or len(stored) < 4:
            return False
        w, s, e, n = stored[0], stored[1], stored[2], stored[3]
        qw, qs, qe, qn = query
        return not (e < qw or w > qe or n < qs or s > qn)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _unjson(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
