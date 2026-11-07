"""Instance-scoped raster weather, served by the canonical Earth host."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from .gfs.layers import LAYER_SPECS, get_layer_definitions, get_layer_spec
from .storage.cache import active_weather_root, read_layer_metadata, weather_cancelled


# GFS runs every 6 hours and is published a few hours after its cycle time, so a cached cycle that
# is at least this old may have a newer one available.
REFRESH_WHEN_CYCLE_OLDER_THAN = timedelta(hours=6)


class WeatherService:
    def __init__(self, root: Path, offline):
        self.root = root
        self.offline = offline
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="earth-weather")
        self.lock = Lock()
        self.pending = set()
        self.errors = {}
        self.stopping = Event()
        self._scheduler: Thread | None = None

    def catalog(self):
        token = active_weather_root.set(self.root)
        try:
            result = []
            for definition in get_layer_definitions():
                item = dict(definition)
                try:
                    metadata = read_layer_metadata(str(item["id"]))
                    item["metadata"] = metadata.model_dump(mode="json") if metadata else None
                except (ValueError, OSError) as exc:
                    item["metadata"] = None
                    self.errors[item["id"]] = str(exc)
                with self.lock:
                    item["refreshing"] = item["id"] in self.pending
                    item["error"] = self.errors.get(item["id"])
                item["offline"] = bool(self.offline())
                result.append(item)
            return result
        finally:
            active_weather_root.reset(token)

    def refresh(self, layer):
        try:
            get_layer_spec(layer)
        except KeyError:
            raise HTTPException(404, "Unknown weather layer")
        if self.offline() or self.stopping.is_set():
            raise HTTPException(409, "Offline: retained weather remains available")
        with self.lock:
            if layer in self.pending:
                return {"status": "refreshing"}
            if self.stopping.is_set():
                raise HTTPException(409, "Weather service is stopping")
            self.pending.add(layer)
            try:
                self.executor.submit(self._refresh, layer)
            except RuntimeError:
                self.pending.discard(layer)
                raise HTTPException(503, "Weather worker is unavailable")
        return {"status": "refreshing"}

    def _refresh(self, layer):
        token = active_weather_root.set(self.root)
        cancel_token = weather_cancelled.set(lambda: self.stopping.is_set() or self.offline())
        try:
            if self.offline():
                return
            from .gfs.refresh_layers import refresh_layer
            refresh_layer(layer)
            with self.lock:
                self.errors.pop(layer, None)
        except Exception as exc:
            with self.lock:
                self.errors[layer] = str(exc)
        finally:
            weather_cancelled.reset(cancel_token)
            active_weather_root.reset(token)
            with self.lock:
                self.pending.discard(layer)

    def due_layers(self, now: datetime | None = None) -> list[str]:
        """Layers with no usable cached data, or whose cached model cycle is old enough to be replaced."""

        now = now or datetime.now(timezone.utc)
        token = active_weather_root.set(self.root)
        try:
            due = []
            for definition in get_layer_definitions():
                layer = str(definition["id"])
                try:
                    metadata = read_layer_metadata(layer)
                except (ValueError, OSError):
                    metadata = None
                if metadata is None or now - metadata.cycle >= REFRESH_WHEN_CYCLE_OLDER_THAN:
                    due.append(layer)
            return due
        finally:
            active_weather_root.reset(token)

    def refresh_due(self, now: datetime | None = None) -> list[str]:
        """Request a refresh for every due layer. Failures are recorded per layer, never raised."""

        requested = []
        for layer in self.due_layers(now):
            try:
                self.refresh(layer)
                requested.append(layer)
            except HTTPException:
                pass  # offline, stopping or unknown: retained data remains available
        return requested

    def start_scheduler(self, interval_seconds: float) -> None:
        """Check for due layers now and then every interval, until close()."""

        if interval_seconds <= 0 or self._scheduler is not None:
            return

        def loop() -> None:
            while not self.stopping.is_set():
                try:
                    self.refresh_due()
                except Exception as exc:  # noqa: BLE001 - the scheduler must outlive any one failure
                    with self.lock:
                        self.errors["scheduler"] = str(exc)
                if self.stopping.wait(interval_seconds):
                    return

        self._scheduler = Thread(target=loop, name="earth-weather-scheduler", daemon=True)
        self._scheduler.start()

    def close(self):
        with self.lock:
            self.stopping.set()
        if self._scheduler is not None:
            self._scheduler.join(timeout=5)
        self.executor.shutdown(wait=True, cancel_futures=True)

    def router(self):
        router = APIRouter()

        @router.get("/api/weather/layers")
        def catalog():
            return self.catalog()

        @router.post("/api/weather/layers/{layer}/refresh", status_code=202)
        def refresh(layer: str):
            return self.refresh(layer)

        @router.get("/weather/gfs/latest/{filename}")
        def asset(filename: str):
            allowed = {"metadata.json"}
            for spec in LAYER_SPECS:
                allowed.update({f"{spec.id}.json", f"{spec.id}.png", f"{spec.id}.f32",
                                f"{spec.id}_speed.png", f"{spec.id}_u.f32", f"{spec.id}_v.f32"})
            path = self.root / "latest" / filename
            if filename not in allowed or not path.is_file():
                raise HTTPException(404, "Weather asset unavailable")
            return FileResponse(path, headers={"Cache-Control": "no-cache"})

        return router
