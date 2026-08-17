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


app = FastAPI(
    title="EarthGlass",
    version="0.2.0",
    description="Renderer-agnostic geospatial layer engine and API.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "earthglass"}


@app.get("/api/layers")
def api_layers() -> list[dict[str, object]]:
    return get_layers()


@app.get("/api/layers/{layer_id}")
def api_layer(layer_id: str) -> dict[str, object]:
    try:
        return registry.get(layer_id).as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/status")
def api_status() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "earthglass",
        "architecture": "geospatial-layer-engine",
        "layers": len(registry.list()),
        "assets": asset_status(),
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    assets = asset_status()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"layers": get_layers(), "assets": assets},
    )
