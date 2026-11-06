"""NOAA CONUS base-reflectivity radar mosaic, served from retained, immutable, time-stamped frames.

Each frame is stored under a name derived from its observation time and is never rewritten, so a
URL always returns the picture that matches the time reported with it.

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
# Older frames kept on disk besides the current one.
RETAINED_FRAMES = 6
FRAME_ID = re.compile(r"^radar-\d{8}T\d{6}Z$")

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

    @staticmethod
    def frame_id(observed_at: str) -> str:
        return "radar-" + parse_timestamp(observed_at).strftime("%Y%m%dT%H%M%SZ")

    def frame_path(self, frame_id: str) -> Path:
        return self.directory / "frames" / f"{frame_id}.png"

    @property
    def meta_path(self) -> Path:
        # Points at the current frame. The frame files themselves are immutable.
        return self.directory / "radar-current.json"

    def _load_meta(self) -> dict[str, Any] | None:
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            parse_timestamp(meta["observed_at"])
            parse_timestamp(meta["retrieved_at"])
            if meta["frame_id"] != self.frame_id(meta["observed_at"]):
                return None
            return meta if self.frame_path(meta["frame_id"]).is_file() else None
        except (OSError, KeyError, ValueError, TypeError):
            return None

    def _atomic_write(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            handle.write(data)
            temp = Path(handle.name)
        temp.replace(target)

    def _prune(self, keep: str) -> None:
        frames = sorted((self.directory / "frames").glob("radar-*.png"), key=lambda p: p.name, reverse=True)
        for old in frames[RETAINED_FRAMES + 1:]:
            if old.stem != keep:
                try:
                    old.unlink()
                except OSError:
                    pass

    def refresh(self) -> dict[str, Any]:
        observed_at = latest_observation_time(self.fetcher(capabilities_url(), self.timeout))
        image = self.fetcher(map_url(observed_at), self.timeout)
        if not image.startswith(b"\x89PNG"):
            raise ValueError("radar GetMap did not return a PNG image")
        frame_id = self.frame_id(observed_at)
        meta = {
            "frame_id": frame_id,
            "observed_at": observed_at,
            "retrieved_at": isoformat(self.clock()),
            "source_url": WMS_BASE,
        }
        # Frame first, metadata last: metadata never points at a missing or partial frame.
        # An existing frame for the same observation is kept as is: frames are immutable.
        if not self.frame_path(frame_id).is_file():
            self._atomic_write(self.frame_path(frame_id), image)
        self._atomic_write(self.meta_path, json.dumps(meta).encode("utf-8"))
        self._prune(frame_id)
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
            "frame_id": meta["frame_id"],
            "image": f"/weather/radar/frames/{meta['frame_id']}.png",
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

        @router.get("/weather/radar/frames/{frame_id}.png")
        def radar_frame(frame_id: str) -> FileResponse:
            # A frame URL names one observation and never changes, so it may be cached forever.
            path = self.frame_path(frame_id)
            if not FRAME_ID.match(frame_id) or not path.is_file():
                raise HTTPException(404, "Radar frame not found")
            return FileResponse(
                path, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"}
            )

        @router.get("/weather/radar/latest.png")
        def radar_image() -> FileResponse:
            # Convenience alias for the current frame. Clients should use the frame URL from the metadata.
            try:
                meta = self.status()
            except RadarUnavailable as exc:
                raise HTTPException(503, "Radar unavailable") from exc
            return FileResponse(
                self.frame_path(meta["frame_id"]), media_type="image/png", headers={"Cache-Control": "no-cache"}
            )

        return router
