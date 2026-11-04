"""NOAA CONUS base-reflectivity radar mosaic, served from a retained, time-stamped frame.

The mosaic comes from the NCEP GeoServer WMS (NOAA/NWS MRMS-derived). The frame's
*observation* time is read from the WMS time dimension and exposed separately from the
time EarthGlass retrieved it, so a consumer can refuse to present an old frame as current.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from earthglass.providers import isoformat, parse_timestamp, utc_now

WMS_BASE = "https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows"
LAYER = "conus_bref_qcd"
BBOX = (-125.0, 24.0, -66.0, 50.0)  # west, south, east, north (CONUS only)
IMAGE_SIZE = (2360, 1040)
ATTRIBUTION = "NOAA / National Weather Service (MRMS base reflectivity)"
USER_AGENT = "EarthGlass/0.4 (+https://github.com/5K-bit/Earthglass)"
# Radar mosaics update about every two minutes; older than this is not "current".
MAX_OBSERVATION_AGE_SECONDS = 15 * 60

Fetcher = Callable[[str, float], bytes]


def fetch_bytes(url: str, timeout: float) -> bytes:
    response = httpx.get(
        url, timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    response.raise_for_status()
    return response.content


def capabilities_url() -> str:
    return f"{WMS_BASE}?service=WMS&version=1.3.0&request=GetCapabilities"


def map_url(observed_at: str) -> str:
    west, south, east, north = BBOX
    width, height = IMAGE_SIZE
    return (
        f"{WMS_BASE}?service=WMS&version=1.1.1&request=GetMap&layers={LAYER}&styles="
        f"&format=image/png&transparent=true&srs=EPSG:4326&bbox={west},{south},{east},{north}"
        f"&width={width}&height={height}&time={observed_at}"
    )


def latest_observation_time(capabilities: bytes) -> str:
    """Newest frame time advertised by the WMS time dimension (a frame that really exists)."""

    text = capabilities.decode("utf-8", errors="replace")
    match = re.search(r'<Dimension[^>]*name="time"[^>]*>([^<]+)</Dimension>', text)
    if not match:
        raise ValueError("radar WMS advertises no time dimension")
    values = [item.strip() for item in match.group(1).split(",") if item.strip()]
    parsed = []
    for value in values:
        try:
            parsed.append(parse_timestamp(value))
        except ValueError:
            continue
    if not parsed:
        raise ValueError("radar WMS time dimension has no valid timestamps")
    return isoformat(max(parsed))


class RadarUnavailable(RuntimeError):
    pass


class RadarService:
    def __init__(
        self,
        directory: Path,
        *,
        refresh_interval: int = 120,
        timeout: float = 20.0,
        fetcher: Fetcher = fetch_bytes,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.directory = directory
        self.refresh_interval = refresh_interval
        self.timeout = timeout
        self.fetcher = fetcher
        self.clock = clock
        self._lock = Lock()
        self._error: str | None = None

    @property
    def image_path(self) -> Path:
        return self.directory / "radar-conus.png"

    @property
    def meta_path(self) -> Path:
        return self.directory / "radar-conus.json"

    def _load_meta(self) -> dict[str, Any] | None:
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            parse_timestamp(meta["observed_at"])
            parse_timestamp(meta["retrieved_at"])
            return meta if self.image_path.is_file() else None
        except (OSError, KeyError, ValueError, TypeError):
            return None

    def _atomic_write(self, target: Path, data: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=self.directory, delete=False) as handle:
            handle.write(data)
            temp = Path(handle.name)
        temp.replace(target)

    def refresh(self) -> dict[str, Any]:
        observed_at = latest_observation_time(self.fetcher(capabilities_url(), self.timeout))
        image = self.fetcher(map_url(observed_at), self.timeout)
        if not image.startswith(b"\x89PNG"):
            raise ValueError("radar GetMap did not return a PNG image")
        meta = {
            "observed_at": observed_at,
            "retrieved_at": isoformat(self.clock()),
            "source_url": WMS_BASE,
        }
        # Image first, metadata last: metadata never points at a missing or partial frame.
        self._atomic_write(self.image_path, image)
        self._atomic_write(self.meta_path, json.dumps(meta).encode("utf-8"))
        self._error = None
        return meta

    def status(self) -> dict[str, Any]:
        """Current frame metadata, refreshing lazily; serves a retained frame on failure."""

        with self._lock:
            meta = self._load_meta()
            needs_refresh = meta is None or (
                (self.clock() - parse_timestamp(meta["retrieved_at"])).total_seconds()
                > self.refresh_interval
            )
            if needs_refresh:
                try:
                    meta = self.refresh()
                except Exception as exc:  # noqa: BLE001 - upstream failure falls back to retained frame
                    self._error = f"{type(exc).__name__}: {exc}"
            if meta is None:
                raise RadarUnavailable(self._error or "radar unavailable")
        now = self.clock()
        observation_age = (now - parse_timestamp(meta["observed_at"])).total_seconds()
        retrieval_age = (now - parse_timestamp(meta["retrieved_at"])).total_seconds()
        stale = (
            observation_age > MAX_OBSERVATION_AGE_SECONDS
            or retrieval_age > max(self.refresh_interval * 3, 360)
        )
        return {
            "product": "conus_base_reflectivity",
            "observed_at": meta["observed_at"],
            "retrieved_at": meta["retrieved_at"],
            "observation_age_seconds": max(0, round(observation_age)),
            "retrieval_age_seconds": max(0, round(retrieval_age)),
            "stale": stale,
            "status": "degraded" if self._error else "ready",
            "error": self._error,
            "bbox": list(BBOX),
            "coverage": "CONUS only",
            "image": "/weather/radar/latest.png",
            "attribution": ATTRIBUTION,
            "source_url": meta.get("source_url", WMS_BASE),
        }

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/weather/radar")
        def radar() -> dict[str, Any]:
            try:
                return self.status()
            except RadarUnavailable as exc:
                raise HTTPException(503, f"Radar unavailable: {exc}") from exc

        @router.get("/weather/radar/latest.png")
        def radar_image() -> FileResponse:
            try:
                self.status()
            except RadarUnavailable as exc:
                raise HTTPException(503, "Radar unavailable") from exc
            return FileResponse(self.image_path, media_type="image/png", headers={"Cache-Control": "no-cache"})

        return router
