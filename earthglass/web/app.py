"""EarthGlass FastAPI application.

The web surface is now an adapter over the renderer-agnostic EarthGlass core.
Leaflet remains a lightweight demo UI; layer definitions live outside the web
package so OBEOS Earth or any other client can consume the same registry.
"""

from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from earthglass.layers import get_layers, registry
from earthglass.providers import ProviderManager, ProviderUnavailable
from earthglass.runtime import provider_manager

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
LEAFLET_JS = STATIC_DIR / "vendor" / "leaflet.js"
LEAFLET_CSS = STATIC_DIR / "vendor" / "leaflet.css"


def asset_status() -> dict[str, object]:
    offline_assets = os.getenv("EARTHGLASS_OFFLINE_ASSETS", "1").strip().lower() not in {"0", "false", "no"}
    local_leaflet_available = LEAFLET_JS.exists() and LEAFLET_CSS.exists()
    online_tiles_enabled = not offline_assets
    map_enabled = online_tiles_enabled or local_leaflet_available
    state = "ok" if map_enabled else "degraded_offline_assets_unavailable"
    return {
        "state": state,
        "offline_assets": offline_assets,
        "local_leaflet_available": local_leaflet_available,
        "online_tiles_enabled": online_tiles_enabled,
        "map_enabled": map_enabled,
        "renderer": "leaflet-demo",
    }


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app(providers: ProviderManager | None = None) -> FastAPI:
    """Build the HTTP adapter; providers can be replaced for deterministic tests."""

    application = FastAPI(
        title="EarthGlass",
        version="0.3.0",
        description="Renderer-agnostic geospatial layer engine and API.",
    )
    application.state.providers = providers or provider_manager
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "earthglass"}

    @application.get("/api/layers")
    def api_layers() -> list[dict[str, object]]:
        return get_layers()

    @application.get("/api/layers/{layer_id}")
    def api_layer(layer_id: str) -> dict[str, object]:
        try:
            return registry.get(layer_id).as_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.get("/api/layers/{layer_id}/features")
    def api_layer_features(layer_id: str) -> dict[str, object]:
        try:
            return application.state.providers.get_features(layer_id).as_geojson()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @application.post("/api/layers/{layer_id}/refresh")
    def api_layer_refresh(layer_id: str) -> dict[str, object]:
        try:
            return application.state.providers.refresh(layer_id).as_geojson()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @application.get("/api/providers/status")
    def api_provider_status() -> list[dict[str, object]]:
        return application.state.providers.statuses()

    @application.get("/api/status")
    def api_status() -> dict[str, object]:
        statuses = application.state.providers.statuses()
        degraded = any(
            item["state"] in {"degraded", "unavailable", "error"}
            for item in statuses
        )
        return {
            "status": "degraded" if degraded else "ok",
            "service": "earthglass",
            "architecture": "geospatial-layer-engine",
            "layers": len(registry.list()),
            "providers": statuses,
            "assets": asset_status(),
        }

    @application.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        assets = asset_status()
        return templates.TemplateResponse(
            request,
            "index.html",
            {"layers": get_layers(), "assets": assets},
        )

    return application


app = create_app()
