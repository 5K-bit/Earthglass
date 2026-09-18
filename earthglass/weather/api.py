"""Instance-scoped raster weather, served by the canonical Earth host."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock, Event
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from .gfs.layers import LAYER_SPECS, get_layer_definitions, get_layer_spec
from .storage.cache import active_weather_root, read_layer_metadata, weather_cancelled


class WeatherService:
    def __init__(self, root: Path, offline):
        self.root = root
        self.offline = offline
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="earth-weather")
        self.lock = Lock()
        self.pending = set()
        self.errors = {}
        self.stopping = Event()

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

    def close(self):
        with self.lock:
            self.stopping.set()
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
