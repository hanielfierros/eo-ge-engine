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

import hashlib
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
    sha256_file,
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
        self.token = _resolve_token(token)
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
        if query.ids:
            body["ids"] = list(query.ids)

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
            asset_name = _pick_small_asset(assets)
        if asset_name not in assets:
            raise NotFoundError(f"asset {asset_name!r} no disponible en {ref.source_id}")

        asset = assets[asset_name]
        href = resolve_official_https_href(asset, asset_name)
        _require_oidc_token_if_needed(asset, self.token)

        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.is_file() and dest.stat().st_size > 0:
            local_sha = sha256_file(dest)
            verification = _verify_official_checksum(asset, dest, local_sha)
            if verification.endswith("_MISMATCH"):
                dest.unlink()
            else:
                return DownloadedResource(
                    path=dest,
                    size_bytes=dest.stat().st_size,
                    checksum=local_sha,
                    checksum_algo="sha256",
                    asset_name=asset_name,
                    source_url=href,
                    checksum_verification=verification,
                )

        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.unlink(missing_ok=True)
        headers = {"User-Agent": "EO-GE-ENGINE/0.15"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                try:
                    response = self._session.get(href, headers=headers, stream=True, timeout=self.timeout)
                except requests.exceptions.Timeout as exc:
                    raise DownloadError("timeout en descarga") from exc
                except requests.exceptions.ConnectionError as exc:
                    raise DownloadError("error de conexion en descarga") from exc
                content_length = None
                with response as r:
                    if r.status_code == 401 or r.status_code == 403:
                        raise AuthenticationError(f"descarga requiere autenticacion (HTTP {r.status_code})")
                    if r.status_code == 404:
                        raise NotFoundError(f"asset no encontrado (HTTP 404) asset={asset_name!r}")
                    if r.status_code == 429:
                        raise RateLimitError("rate limit (429) en descarga")
                    if r.status_code >= 500:
                        raise DownloadError(f"error de servidor (HTTP {r.status_code})")
                    if r.status_code != 200:
                        raise DownloadError(f"descarga devolvio HTTP {r.status_code}")
                    content_length = r.headers.get("Content-Length")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                fh.write(chunk)
                if not tmp.is_file() or tmp.stat().st_size == 0:
                    tmp.unlink(missing_ok=True)
                    raise IntegrityError("archivo descargado vacio o ausente")
                if content_length:
                    try:
                        expected = int(content_length)
                    except (TypeError, ValueError):
                        expected = None
                    if expected is not None and tmp.stat().st_size != expected:
                        tmp.unlink(missing_ok=True)
                        raise IntegrityError("tamano descargado distinto de Content-Length")
                tmp.replace(dest)
                last_exc = None
                break
            except (RateLimitError, DownloadError, IntegrityError) as exc:
                last_exc = exc
                tmp.unlink(missing_ok=True)
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.backoff_seconds * (2 ** attempt))
            except (AuthenticationError, NotFoundError, UnsupportedAssetError):
                tmp.unlink(missing_ok=True)
                raise
        if last_exc is not None:
            raise last_exc

        local_sha = sha256_file(dest)
        verification = _verify_official_checksum(asset, dest, local_sha)
        if verification.endswith("_MISMATCH"):
            dest.unlink(missing_ok=True)
            raise IntegrityError("checksum oficial no coincide")
        return DownloadedResource(
            path=dest,
            size_bytes=dest.stat().st_size,
            checksum=local_sha,
            checksum_algo="sha256",
            asset_name=asset_name,
            source_url=href,
            checksum_verification=verification,
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
                "tile": _normalize_tile(props.get("grid:code"), ref.source_id),
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
                "checksum_verification": resource.checksum_verification,
                "checksum_algo": resource.checksum_algo,
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


def _normalize_tile(value: str | None, source_id: str | None = None) -> str | None:
    """Normaliza grid:code CDSE ('MGRS-12RYP') a tile MGRS ('T12RYP')."""
    if value:
        text = str(value).strip().upper()
        if text.startswith("MGRS-") and len(text) >= 10:
            text = "T" + text.split("-", 1)[1]
        if text.startswith("T") and len(text) == 6 and text[1:3].isdigit():
            return text
    if source_id:
        return _tile_from_id(source_id)
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


def _resolve_token(explicit: str | None) -> str | None:
    """Resuelve el token OIDC. No registra ni devuelve el valor en errores.

    Orden: argumento explicito, luego CDSE_TOKEN, luego CDSE_ACCESS_TOKEN
    (alias documentado por CDSE). Cadena vacia = ausente.
    """
    if explicit is not None:
        text = str(explicit).strip()
        return text or None
    for key in ("CDSE_TOKEN", "CDSE_ACCESS_TOKEN"):
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return str(raw).strip()
    return None


def _iter_alternate_entries(asset: dict[str, Any]) -> list[dict[str, Any]]:
    alternate = asset.get("alternate")
    if not isinstance(alternate, dict):
        return []
    entries: list[dict[str, Any]] = []
    for value in alternate.values():
        if isinstance(value, dict):
            entries.append(value)
    return entries


def resolve_official_https_href(asset: dict[str, Any], asset_name: str) -> str:
    """Devuelve un href HTTP(S) oficialmente declarado por el asset STAC.

    No transforma s3://bucket/key en una URL inventada. Solo acepta:
    - href primario http(s);
    - alternate.*.href http(s) publicado por CDSE/STAC (p. ej. alternate.https).
    """
    href = str((asset or {}).get("href") or "")
    if href.startswith("https://") or href.startswith("http://"):
        return href
    if href.startswith("s3://"):
        for entry in _iter_alternate_entries(asset):
            alt_href = str(entry.get("href") or "")
            if alt_href.startswith("https://") or alt_href.startswith("http://"):
                return alt_href
        raise UnsupportedAssetError(
            f"asset {asset_name!r} usa s3:// y no declara alternate HTTPS oficial"
        )
    if not href:
        raise UnsupportedAssetError(f"asset {asset_name!r} sin href")
    raise UnsupportedAssetError(
        f"esquema no soportado para asset {asset_name!r}"
    )


def _auth_refs(asset: dict[str, Any]) -> list[str]:
    refs = [str(x).lower() for x in (asset.get("auth:refs") or [])]
    for entry in _iter_alternate_entries(asset):
        refs.extend(str(x).lower() for x in (entry.get("auth:refs") or []))
    return refs


def _require_oidc_token_if_needed(asset: dict[str, Any], token: str | None) -> None:
    refs = _auth_refs(asset)
    needs_oidc = any(r in {"oidc", "oauth", "openidconnect", "openid-connect"} for r in refs)
    if needs_oidc and not token:
        raise AuthenticationError(
            "descarga requiere autenticacion OIDC (variable CDSE_TOKEN ausente)"
        )


def comparable_sha256(asset: dict[str, Any]) -> str | None:
    """SHA-256 comparable solo si el proveedor lo declara de forma inequívoca."""
    parsed = parse_official_checksum(asset)
    if parsed and parsed[0] == "sha256":
        return parsed[1]
    return None


def parse_official_checksum(asset: dict[str, Any]) -> tuple[str, str] | None:
    """Interpreta checksum STAC/CDSE. No adivina el algoritmo.

    Multihash hex: 1220 = sha2-256 (32 bytes), 1620 = sha3-256 (32 bytes).
    """
    candidates: list[str] = []
    for key in ("file:checksum", "checksum", "checksum:multihash"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip().lower())
    for text in candidates:
        if text.startswith("sha256:"):
            text = text[7:]
        if text.startswith("sha3-256:") or text.startswith("sha3_256:"):
            digest = text.split(":", 1)[1]
            if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                return ("sha3_256", digest)
        if len(text) == 68 and all(c in "0123456789abcdef" for c in text):
            if text.startswith("1220"):
                return ("sha256", text[4:])
            if text.startswith("1620"):
                return ("sha3_256", text[4:])
        if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
            return ("sha256", text)
    return None


def _file_digest(path: Path, algo: str) -> str:
    if algo == "sha256":
        return sha256_file(path)
    if algo == "sha3_256":
        digest = hashlib.sha3_256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    raise IntegrityError("algoritmo de checksum oficial no soportado")


def _verify_official_checksum(asset: dict[str, Any], path: Path, local_sha256: str) -> str:
    parsed = parse_official_checksum(asset)
    if parsed is None:
        return "SHA-256_LOCAL"
    algo, expected = parsed
    actual = local_sha256 if algo == "sha256" else _file_digest(path, algo)
    if actual != expected:
        return f"OFFICIAL_{algo.upper()}_MISMATCH"
    if algo == "sha256":
        return "OFFICIAL_SHA256_MATCH"
    if algo == "sha3_256":
        return "OFFICIAL_SHA3_256_MATCH"
    return "SHA-256_LOCAL"


def declared_raster_metadata(asset: dict[str, Any]) -> dict[str, Any]:
    """Metadata raster declarada por STAC. No inventa ni aplica scaling."""
    epsg = asset.get("proj:epsg")
    code = asset.get("proj:code")
    if not code and epsg is not None:
        code = f"EPSG:{epsg}"
    out: dict[str, Any] = {}
    if code:
        out["proj_code"] = code
    if epsg is not None:
        out["proj_epsg"] = epsg
    if asset.get("proj:shape") is not None:
        out["proj_shape"] = asset.get("proj:shape")
    if asset.get("gsd") is not None:
        out["gsd"] = asset.get("gsd")
    dtype = asset.get("data_type") or asset.get("raster:data_type")
    if dtype is not None:
        out["data_type"] = dtype
    if "nodata" in asset:
        out["nodata"] = asset.get("nodata")
    if "raster:scale" in asset:
        out["raster_scale"] = asset.get("raster:scale")
    if "raster:offset" in asset:
        out["raster_offset"] = asset.get("raster:offset")
    if asset.get("type"):
        out["media_type"] = asset.get("type")
    return out
