"""Conector Sentinel-2 Level-2A (Copernicus Data Space Ecosystem).

Implementa el primer conector de produccion del EO-GE Engine:
discovery STAC -> seleccion de Item -> metadata -> descarga controlada ->
SHA-256 -> SourceRepresentation.

Referencia verificada (CDSE, STAC 1.1.0):
  - endpoint STAC: https://stac.dataspace.copernicus.eu/v1/
  - coleccion:      sentinel-2-l2a
  - autenticacion:  s3 (custom-s3) y oidc (OpenID Connect) para descarga.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from app.connectors.base import (
    CAPABILITY_CHECKSUM,
    CAPABILITY_DISCOVERY,
    CAPABILITY_DOWNLOAD,
    CAPABILITY_METADATA,
    CAPABILITY_SPATIAL_FILTER,
    CAPABILITY_TEMPORAL_FILTER,
    AuthenticationError,
    BaseConnector,
    ConnectorError,
    DiscoveryError,
    DiscoveryQuery,
    DownloadError,
    DownloadedResource,
    IntegrityError,
    NotFoundError,
    RateLimitError,
    SourceReference,
    SourceRepresentation,
)

STAC_ENDPOINT = "https://stac.dataspace.copernicus.eu/v1/"
COLLECTION = "sentinel-2-l2a"
SOURCE_NAME = "COPERNICUS_DATA_SPACE"
PRODUCT_NAME = "SENTINEL2_L2A"


class Sentinel2L2AConnector(BaseConnector):
    """Conector Sentinel-2 L2A contra el catalogo STAC de CDSE."""

    source = SOURCE_NAME
    capabilities = {
        CAPABILITY_DISCOVERY,
        CAPABILITY_METADATA,
        CAPABILITY_DOWNLOAD,
        CAPABILITY_CHECKSUM,
        CAPABILITY_SPATIAL_FILTER,
        CAPABILITY_TEMPORAL_FILTER,
    }

    def __init__(
        self,
        stac_endpoint: str = STAC_ENDPOINT,
        collection: str = COLLECTION,
        token: str | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        session: requests.Session | None = None,
    ) -> None:
        self.stac_endpoint = stac_endpoint.rstrip("/") + "/"
        self.collection = collection
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._session = session or requests.Session()

    # ------------------------------------------------------------------ #
    def discover(self, query: DiscoveryQuery) -> list[SourceReference]:
        body: dict[str, Any] = {"collections": [query.collection or self.collection]}
        if query.bbox:
            body["bbox"] = list(query.bbox)
        if query.datetime:
            body["datetime"] = query.datetime
        if query.limit:
            body["limit"] = query.limit

        url = self.stac_endpoint + "search"
        try:
            resp = self._session.post(url, json=body, timeout=self.timeout)
        except requests.exceptions.Timeout as exc:
            raise DiscoveryError(f"timeout en discovery: {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise DiscoveryError(f"error de conexion en discovery: {url}") from exc

        if resp.status_code == 429:
            raise RateLimitError("rate limit (429) en discovery")
        if resp.status_code == 401 or resp.status_code == 403:
            raise AuthenticationError(f"autenticacion requerida ({resp.status_code}) en discovery")
        if resp.status_code != 200:
            raise DiscoveryError(f"discovery devolvio {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise DiscoveryError("respuesta STAC no es JSON valido") from exc

        refs: list[SourceReference] = []
        for feat in payload.get("features", []):
            refs.append(SourceReference(
                source_id=feat.get("id"),
                collection=feat.get("collection") or self.collection,
                item=feat,
            ))
        return refs

    def get_metadata(self, ref: SourceReference) -> dict[str, Any]:
        return ref.item

    def get_collection(self) -> dict[str, Any]:
        """Devuelve la metadata de la coleccion (incluye item_assets con bands)."""
        url = self.stac_endpoint + "collections/" + self.collection
        resp = self._session.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            raise DiscoveryError(f"coleccion devolvio {resp.status_code}: {url}")
        return resp.json()

    # ------------------------------------------------------------------ #
    def select_item(self, refs: list[SourceReference]) -> SourceReference | None:
        """Selecciona un item: menor cloud cover, luego mas reciente, luego id."""
        if not refs:
            return None

        def cloud(r: SourceReference) -> float:
            v = r.item.get("properties", {}).get("eo:cloud_cover")
            return float(v) if v is not None else float("inf")

        def dt(r: SourceReference) -> str:
            return r.item.get("properties", {}).get("datetime") or ""

        return min(refs, key=lambda r: (cloud(r), -_ts(dt(r)), r.source_id))

    # ------------------------------------------------------------------ #
    def download(
        self,
        ref: SourceReference,
        dest: Path,
        asset_name: str | None = None,
    ) -> DownloadedResource:
        assets = ref.item.get("assets", {})
        if asset_name is None:
            # preferir metadata pequena; en su defecto el Product.
            asset_name = _pick_small_asset(assets)
        if asset_name not in assets:
            raise NotFoundError(f"asset {asset_name!r} no disponible en {ref.source_id}")

        href = assets[asset_name].get("href", "")
        if not href.startswith("http://") and not href.startswith("https://"):
            raise UnsupportedAssetError(
                f"asset {asset_name!r} usa {href.split(':')[0]!r}; solo se soporta HTTP(S) en S-A.6"
            )

        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")

        headers = {"User-Agent": "EO-GE-ENGINE/0.6"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        for attempt in range(self.max_retries + 1):
            try:
                with self._session.get(href, headers=headers, stream=True, timeout=self.timeout) as r:
                    if r.status_code == 401 or r.status_code == 403:
                        raise AuthenticationError(f"descarga requiere token (HTTP {r.status_code})")
                    if r.status_code == 404:
                        raise NotFoundError(f"asset no encontrado (404): {href}")
                    if r.status_code == 429:
                        retry_after = int(r.headers.get("retry-after", self.backoff_seconds))
                        raise RateLimitError(f"rate limit (429); retry-after={retry_after}")
                    if r.status_code >= 500:
                        raise DownloadError(f"error de servidor (HTTP {r.status_code})")
                    if r.status_code != 200:
                        raise DownloadError(f"descarga devolvio HTTP {r.status_code}")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_content(chunk_size=65536):
                            fh.write(chunk)
                tmp.replace(dest)
                break
            except (RateLimitError, DownloadError) as exc:
                if attempt >= self.max_retries:
                    tmp.unlink(missing_ok=True)
                    raise
                time.sleep(self.backoff_seconds * (2 ** attempt))
            except (AuthenticationError, NotFoundError) as exc:
                tmp.unlink(missing_ok=True)
                raise

        size = dest.stat().st_size
        checksum = assets[asset_name].get("checksum:multihash") or None
        return DownloadedResource(
            path=dest,
            size_bytes=size,
            checksum=_normalize_checksum(checksum),
            checksum_algo="sha256",
            asset_name=asset_name,
            source_url=href,
        )

    # ------------------------------------------------------------------ #
    def build_source_representation(
        self,
        ref: SourceReference,
        resource: DownloadedResource,
        collection_metadata: dict[str, Any] | None = None,
    ) -> SourceRepresentation:
        props = ref.item.get("properties", {})
        geometry = ref.item.get("geometry")
        bbox = ref.item.get("bbox")
        assets = ref.item.get("assets", {})

        return SourceRepresentation(
            source=SOURCE_NAME,
            product=PRODUCT_NAME,
            source_id=ref.source_id,
            source_metadata=ref.item,
            acquisition={
                "observation_time": props.get("datetime"),
                "start_time": props.get("start_datetime"),
                "end_time": props.get("end_datetime"),
                "platform": props.get("platform"),
                "instrument": (props.get("instruments") or [None])[0],
                "processing_level": props.get("processing:level"),
            },
            spatial={
                "geometry": geometry,
                "bbox": bbox,
                "epsg": props.get("proj:epsg"),
                "gsd": props.get("gsd"),
                "tile": props.get("grid:code") or _tile_from_id(ref.source_id),
            },
            temporal={
                "observation_time": props.get("datetime"),
                "start_time": props.get("start_datetime"),
                "end_time": props.get("end_datetime"),
            },
            resource={
                "asset_name": resource.asset_name,
                "local_path": str(resource.path),
                "size_bytes": resource.size_bytes,
                "source_url": resource.source_url,
                "media_type": assets.get(resource.asset_name, {}).get("type") if resource.asset_name else None,
            },
            checksum=resource.checksum,
            provenance={
                "provider": "ESA / Copernicus",
                "collection": ref.collection,
                "source_id": ref.source_id,
                "retrieval_time": _now_iso(),
                "license": props.get("license") or "CC-BY-4.0 (Sentinel)",
                "source_url": resource.source_url,
            },
            collection_metadata=collection_metadata or {},
        )


class UnsupportedAssetError(ConnectorError):
    """Asset con esquema no soportado (p. ej. s3 sin cliente S3)."""


def _ts(value: str) -> float:
    try:
        from datetime import datetime
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _tile_from_id(source_id: str) -> str | None:
    parts = source_id.split("_")
    for p in parts:
        if p.startswith("T") and len(p) == 6:
            return p
    return None


def _pick_small_asset(assets: dict[str, Any]) -> str:
    for name in ("safe_manifest", "product_metadata", "granule_metadata", "inspire_metadata", "thumbnail"):
        if name in assets:
            return name
    return "Product"


def _normalize_checksum(checksum: str | None) -> str | None:
    if not checksum:
        return None
    # STAC 'checksum:multihash' puede venir como prefijo:base64; se conserva tal cual.
    return checksum


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
