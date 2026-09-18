"""Private-only gateway with an optional bundled viewer; no public observation API."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .api import build_presence_app


def build_presence_gateway(store, assets: Path | None = None, *, require_tls=True):
    private = build_presence_app(store, require_tls=require_tls)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def boundary(request, call_next):
        if require_tls and request.url.scheme != "https":
            return JSONResponse(
                {"error": "encrypted_transport_required"}, status_code=403
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; "
            "img-src 'self' data: blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    app.mount("/private", private)
    if assets is not None and (assets / "presence.html").is_file():

        @app.get("/")
        def home():
            return FileResponse(assets / "presence.html")

        app.mount("/", StaticFiles(directory=assets), name="private-viewer")
    return app
