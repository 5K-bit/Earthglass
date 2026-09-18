"""Owns provider lifetimes, quotas, history, and renderer-independent snapshots."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, timedelta
from pathlib import Path

from ..mobility.static_gtfs import StaticGTFSFeed
from ..mobility.traffic import NY511Feed, NYCDOTFeed
from ..mobility.transit import default_transit
from .feeds.aviation import AircraftFeed
from .feeds.documents import ImageryFeed, SpaceWeatherFeed
from .feeds.environment import (
    EarthquakeFeed,
    FiresFeed,
    TemperatureFeed,
    WeatherFeed,
    WeatherFieldFeed,
)
from .feeds.local_context import (
    BikeshareFeed,
    CaltransCameraFeed,
    InfrastructureFeed,
    TfLCameraFeed,
    TrafficFeed,
)
from .feeds.orbits import GROUPS, OrbitalFeed
from .feeds.perception import PerceptionFeed
from .feeds.planetary import AviationWeatherFeed, EonetFeed, NWSAlertFeed
from .feeds.space import LaunchFeed
from .geometry import observation_in_view
from .history import SpatialHistory
from .models import Observation, ProviderHealth, Viewport, utc_now
from .network import ProviderError, PublicHTTP


def default_feeds(http, credentials=None):
    """Local-first sources; named free-key feeds are optional and never required at startup."""
    credentials = credentials or (lambda _: None)
    classes = [
        AircraftFeed,
        EarthquakeFeed,
        FiresFeed,
        NWSAlertFeed,
        EonetFeed,
        ImageryFeed,
        SpaceWeatherFeed,
        WeatherFeed,
        TemperatureFeed,
        InfrastructureFeed,
        LaunchFeed,
        BikeshareFeed,
        TrafficFeed,
        TfLCameraFeed,
        PerceptionFeed,
    ]
    return [StaticGTFSFeed(http), StaticGTFSFeed(http, stops=True), NYCDOTFeed(http, credentials)] + [NY511Feed(http, credentials, product=p) for p in ("incidents","cameras","conditions")] + default_transit(http, credentials) + [OrbitalFeed(http, credentials, group=group) for group in GROUPS] + [WeatherFieldFeed(http, credentials, field=field) for field in ("wind", "precipitation", "pressure", "clouds")] + [cls(http, credentials) for cls in classes] + [AviationWeatherFeed(http, credentials, product=p) for p in ("metar", "taf", "sigmet", "gairmet", "pirep")] + [
        CaltransCameraFeed(http, district=3),
        CaltransCameraFeed(http, district=4),
    ]


class SpatialEngine:
    def __init__(
        self,
        data_dir: Path,
        *,
        credentials=lambda _: None,
        feeds=None,
        on_observations=None,
        http=None,
        history=None,
        on_resync=None,
    ):
        self.http = http or PublicHTTP()
        self.history = history or SpatialHistory(
            Path(data_dir) / "observations.sqlite3"
        )
        self.on_observations = on_observations
        self.on_resync = on_resync
        self.maintenance_error = None
        self.delivery_error = None
        self._next_delivery = 0.0
        self._offline = False
        self.viewport = Viewport(west=-180, south=-90, east=180, north=90)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="earthglass")
        self._volatile = {}
        self._entries = {}
        self._watch_path = Path(data_dir) / "watches.json"
        raw_watches = (
            json.loads(self._watch_path.read_text(encoding="utf-8"))
            if self._watch_path.exists()
            else {}
        )
        self.watches = {
            name: Viewport.model_validate(value)
            for name, value in list(raw_watches.items())[:10]
        }
        for feed in (
            feeds if feeds is not None else default_feeds(self.http, credentials)
        ):
            spec = feed.spec
            if hasattr(feed, "configure_cache"):
                feed.configure_cache(Path(data_dir) / "provider-cache")
            self._entries[spec.id] = {
                "feed": feed,
                "enabled": False,
                "generation": 0,
                "future": None,
                "next": 0.0,
                "last_started": 0.0,
                "viewport_dirty": False,
                "failures": 0,
                "area_index": 0,
                "stream_stop": threading.Event(),
                "stream_thread": None,
                "health": ProviderHealth(
                    provider=spec.id,
                    layer=spec.layer,
                    coverage=spec.coverage,
                    attribution=spec.attribution,
                    credential_required=spec.credential,
                    transport=spec.transport,
                ),
            }

        from datetime import datetime

        for cached in self.history.cached_providers():
            ident = {"opensky": "adsb", "overpass_roads": "traffic"}.get(cached["provider"], cached["provider"])
            if ident in self._entries:
                health = self._entries[ident]["health"]
                health.count = cached["count"]
                health.last_success_at = datetime.fromtimestamp(
                    cached["received"], UTC
                )
                health.state = "stale"
                health.message = "Retained observations; awaiting live verification"

        for entry in self._entries.values():
            feed=entry["feed"]
            if hasattr(feed,"document") and feed.document().get("retrieved_at"):
                entry["health"].last_success_at=datetime.fromisoformat(feed.document()["retrieved_at"])
                entry["health"].count=1
                entry["health"].state="stale"
        self._network_path = Path(data_dir) / "network.json"
        if self._network_path.exists():
            policy = json.loads(self._network_path.read_text(encoding="utf-8"))
            self.set_offline(policy.get("mode") == "offline", persist=False)

    @property
    def offline(self):
        return self._offline

    @offline.setter
    def offline(self, value):
        self.set_offline(value, persist=False)

    def set_offline(self, offline, *, persist=True):
        """Pause public acquisition while local perception and storage keep working."""
        with self._lock:
            if persist:
                self._network_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._network_path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"mode": "offline" if offline else "auto"}), encoding="utf-8")
                temporary.replace(self._network_path)
            self.http.offline = bool(offline)
            if self._offline != bool(offline):
                self._offline = bool(offline)
                for entry in self._entries.values():
                    if entry["feed"].spec.local:
                        continue
                    entry["generation"] += 1
                    entry["stream_stop"].set()
                    entry["health"].lifecycle = "idle" if entry["enabled"] else "disabled"
                if offline:
                    self._volatile.clear()
            return self.network_status()

    def network_status(self):
        return {"mode": "offline" if self.offline else "auto", "access": "public_with_optional_free_keys", "local_processing": True}

    def catalog(self):
        with self._lock:
            now = utc_now()
            result = []
            for entry in self._entries.values():
                health = entry["health"].model_copy(deep=True)
                if (
                    entry["enabled"]
                    and health.last_success_at
                    and (now - health.last_success_at).total_seconds()
                    > entry["feed"].spec.interval_seconds * 3
                ):
                    health.state = "stale" if health.count else "offline"
                if self.offline and not entry["feed"].spec.local:
                    health.state = "stale" if health.count else "offline"
                    health.message = "Offline mode; retained observations only"
                result.append(
                    {
                        **asdict(entry["feed"].spec),
                        "enabled": entry["enabled"],
                        "health": health.model_dump(mode="json"),
                    }
                )
            return result

    def set_watch(self, name, viewport=None):
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise ValueError("Watch name must contain 1–80 characters")
        with self._lock:
            if viewport is None:
                self.watches.pop(name, None)
            else:
                if name not in self.watches and len(self.watches) >= 10:
                    raise ValueError("Maximum 10 watched areas")
                self.watches[name] = (
                    viewport
                    if isinstance(viewport, Viewport)
                    else Viewport.model_validate(viewport)
                )
            self._watch_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._watch_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {name: area.model_dump() for name, area in self.watches.items()},
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary.replace(self._watch_path)
            for entry in self._entries.values():
                if entry["feed"].spec.transport == "websocket":
                    entry["stream_stop"].set()
                    entry["generation"] += 1
        return self.watch_list()

    def watch_list(self):
        with self._lock:
            return [
                {"name": name, **area.model_dump()}
                for name, area in self.watches.items()
            ]

    def set_viewport(self, viewport):
        viewport = (
            viewport
            if isinstance(viewport, Viewport)
            else Viewport.model_validate(viewport)
        )
        with self._lock:
            if viewport == self.viewport:
                return
            self.viewport = viewport
            for entry in self._entries.values():
                entry["viewport_dirty"] = True
                entry["area_index"] = 0
                code = entry["health"].error_code
                if code in {None, "zoom_required", "dateline_viewport"}:
                    # Navigation may query a new area without waiting for a catalog refresh.
                    # Upstream failures keep their existing backoff; requests remain bounded.
                    earliest = 0.0 if code else entry["last_started"] + min(30, entry["feed"].spec.interval_seconds)
                    entry["next"] = min(entry["next"], earliest)
                if entry["feed"].spec.transport == "websocket":
                    entry["stream_stop"].set()
                    entry["generation"] += 1

    def enable(self, layer, enabled=True):
        with self._lock:
            entries = [
                entry
                for entry in self._entries.values()
                if entry["feed"].spec.layer == layer or entry["feed"].spec.id == layer
            ]
            if not entries:
                raise KeyError(f"Unknown layer: {layer}")
            for entry in entries:
                if entry["enabled"] == enabled:
                    continue
                entry["enabled"] = enabled
                entry["generation"] += 1
                entry["health"].lifecycle = "idle" if enabled else "disabled"
                entry["health"].message = (
                    "Waiting for provider" if enabled else "Disabled"
                )
                entry["stream_stop"].set()
                if enabled:
                    entry["next"] = max(entry["next"], time.monotonic())
        return self.catalog()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if self._stop.is_set():
                raise RuntimeError("A stopped engine cannot be restarted")
            self._thread = threading.Thread(
                target=self._run, name="earthglass-scheduler", daemon=True
            )
            self._thread.start()

    def _run(self):
        maintenance = 0.0
        while not self._stop.wait(0.25):
            self.tick()
            self.flush_publications()
            if time.monotonic() >= maintenance:
                try:
                    self.history.prune()
                    self.maintenance_error = None
                except Exception as exc:
                    self.maintenance_error = type(exc).__name__
                maintenance = time.monotonic() + 60

    def tick(self):
        with self._lock:
            for entry in self._entries.values():
                if not entry["enabled"] or time.monotonic() < entry["next"] or (self.offline and not entry["feed"].spec.local):
                    continue
                if entry["feed"].spec.transport == "websocket":
                    thread = entry["stream_thread"]
                    if thread and thread.is_alive():
                        continue
                    entry["stream_stop"] = threading.Event()
                    thread = threading.Thread(
                        target=self._stream,
                        args=(entry, entry["generation"], self.viewport),
                        name="earthglass-ais",
                        daemon=True,
                    )
                    entry["stream_thread"] = thread
                    thread.start()
                else:
                    if entry["future"] is not None and not entry["future"].done():
                        continue
                    entry["last_started"] = time.monotonic()
                    entry["viewport_dirty"] = False
                    entry["health"].last_attempt_at = utc_now()
                    entry["health"].lifecycle = "loading"
                    entry["health"].state = "recovering"
                    entry["health"].message = "Refreshing"
                    areas = [self.viewport, *self.watches.values()]
                    area = areas[entry["area_index"] % len(areas)]
                    entry["area_index"] += 1
                    entry["future"] = self._pool.submit(
                        self._fetch, entry, entry["generation"], area
                    )

    def _fetch(self, entry, generation, viewport):
        try:
            if self.offline and not entry["feed"].spec.local:
                return
            entry["feed"].rejected = 0
            values = entry["feed"].fetch(viewport, utc_now())
            self._accept(entry, generation, values)
        except Exception as exc:
            self._failed(entry, generation, exc)

    def _stream(self, entry, generation, viewport):
        entry["health"].lifecycle = "loading"
        entry["health"].state = "recovering"
        try:
            pending = {}
            last_flush = time.monotonic()

            def emit(values):
                nonlocal last_flush
                for observation in values:
                    pending[observation.entity_id] = observation
                if time.monotonic() - last_flush >= 1 or len(pending) >= 250:
                    self._accept(entry, generation, list(pending.values())[:250])
                    pending.clear()
                    last_flush = time.monotonic()

            entry["feed"].watch_viewports = list(self.watches.values())
            entry["feed"].run(viewport, emit, entry["stream_stop"])
            if pending:
                self._accept(entry, generation, list(pending.values()))
        except Exception as exc:
            self._failed(entry, generation, exc)

    def _accept(self, entry, generation, observations):
        with self._lock:
            if (
                self._stop.is_set()
                or generation != entry["generation"]
                or not entry["enabled"]
                or (self.offline and not entry["feed"].spec.local)
            ):
                return
            now = utc_now()
            durable = []
            for observation in observations[: entry["feed"].spec.max_records]:
                observation = (
                    observation
                    if isinstance(observation, Observation)
                    else Observation.model_validate(observation)
                )
                if not any(
                    observation_in_view(observation, area)
                    for area in [self.viewport, *self.watches.values()]
                ):
                    continue
                retention = observation.properties.get("retention_seconds")
                if retention is not None:
                    # Provider-restricted live data is never put in the disk history or event backbone.
                    self._volatile[observation.entity_id] = (
                        time.monotonic() + min(float(retention), 120),
                        observation.wire(),
                    )
                else:
                    durable.append(observation)
            self.history.ingest(durable)
            entry["failures"] = 0
            delay = entry["feed"].spec.interval_seconds
            if entry["viewport_dirty"] or self.watches:
                delay = min(30, delay)
            entry["next"] = time.monotonic() + delay
            health = entry["health"]
            health.lifecycle = "running"
            health.state = "degraded" if entry["feed"].rejected else "online"
            health.count = len(observations) or (1 if hasattr(entry["feed"], "document") and entry["feed"].document().get("data") else 0)
            health.rejected_records = entry["feed"].rejected
            health.last_success_at = now
            health.next_attempt_at = now + timedelta(
                seconds=delay
            )
            health.error_code = None
            health.message = getattr(entry["feed"], "status_message", None) or (
                "No observations in this coverage" if not health.count else "Updated"
            )
            if any(item.properties.get("elements_stale") for item in observations):
                health.state = "degraded"
                health.message = "Predictions use retained orbital elements; source refresh is unavailable"
            if any(item.properties.get("fallback") for item in observations):
                health.state = "degraded"
                health.message = "Using separately attributed fallback provider"

    def flush_publications(self):
        if not self.on_observations or time.monotonic() < self._next_delivery:
            return
        status = self.history.publication_status()
        if status["resync_required"] and self.on_resync:
            try:
                self.on_resync(self.history.query(limit=1))
                self.history.acknowledge_publication_resync(status["resync_revision"])
            except Exception as exc:
                self.delivery_error = type(exc).__name__
                self._next_delivery = time.monotonic() + 10
                return
        changes = self.history.pending_publications(100)
        if not changes:
            return
        try:
            self.on_observations(changes)
            self.history.acknowledge_publications(changes)
            self.delivery_error = None
            self._next_delivery = time.monotonic() + 2
        except Exception as exc:
            self.delivery_error = type(exc).__name__
            self._next_delivery = time.monotonic() + 10

    def _failed(self, entry, generation, error):
        with self._lock:
            if generation != entry["generation"] or self._stop.is_set():
                return
            entry["failures"] += 1
            spec = entry["feed"].spec
            delay = min(
                3600,
                max(spec.interval_seconds, 15) * 2 ** min(entry["failures"] - 1, 6),
            )
            entry["next"] = time.monotonic() + delay
            health = entry["health"]
            health.lifecycle = "idle"
            health.state = "degraded" if health.last_success_at else "offline"
            health.error_code = (
                error.code if isinstance(error, ProviderError) else "provider_error"
            )
            health.message = (
                str(error)
                if isinstance(error, ProviderError)
                else "Provider failed; details were excluded to protect credentials"
            )
            if entry["viewport_dirty"] and health.error_code in {"zoom_required", "dateline_viewport"}:
                entry["next"] = time.monotonic()
                delay = 0
            health.next_attempt_at = utc_now() + timedelta(seconds=delay)

    def configure_perception(self, event_reader, cameras):
        """Wire the local perception feed. Returns False when that provider is absent."""
        entry = self._entries.get("project3000")
        if entry is None:
            return False
        entry["feed"].configure(event_reader, cameras)
        return True

    def search(self, text, *, at=None, limit=50):
        """History matches first, then any still-live volatile contacts."""
        matches = self.history.search(text, at=at, limit=limit)
        if at is not None or len(matches) >= limit:
            return matches[:limit]
        needle = str(text).strip().lower()
        with self._lock:
            for expiry, item in list(self._volatile.values()):
                if expiry <= time.monotonic():
                    continue
                name = (item.get("properties") or {}).get("name")
                if (
                    needle in ("" if name is None else str(name).lower())
                    or needle in str(item["entity_id"]).lower()
                ):
                    matches.append(item)
                    if len(matches) >= limit:
                        break
        return matches[:limit]

    def query(self, **kwargs):
        payload = self.history.query(**kwargs)
        viewport = kwargs.get("viewport")
        with self._lock:
            self._volatile = {
                ident: value
                for ident, value in self._volatile.items()
                if value[0] > time.monotonic()
            }
            if kwargs.get("at") is None and kwargs.get("since") is None:
                payload["volatile_observations"] = [
                    value[1]
                    for value in self._volatile.values()
                    if (
                        not kwargs.get("entity_id")
                        or value[1]["entity_id"] == kwargs["entity_id"]
                    )
                    and (
                        not kwargs.get("layers")
                        or value[1]["layer"] in kwargs["layers"]
                    )
                    and (
                        viewport is None
                        or viewport.contains(
                            Observation.model_validate(value[1]).position
                        )
                    )
                ]
            else:
                payload["volatile_observations"] = []
        if kwargs.get("at") is not None:
            from .temporal import project_weather
            payload["observations"]=[projected for value in payload["observations"] if (projected:=project_weather(value,kwargs["at"])) is not None]
        return payload

    def stop(self):
        self._stop.set()
        self.http.offline = True
        with self._lock:
            for entry in self._entries.values():
                entry["enabled"] = False
                entry["generation"] += 1
                entry["stream_stop"].set()
                entry["health"].lifecycle = "stopped"
        if self._thread:
            self._thread.join(timeout=2)
        for entry in self._entries.values():
            if entry["stream_thread"]:
                entry["stream_thread"].join(timeout=2)
        self._pool.shutdown(wait=True, cancel_futures=True)
        self.http.close()
        self.history.close()
