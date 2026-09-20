"""Serve installed reference labels through the existing authenticated Earth host."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def reference_router(root: Path):
    router = APIRouter()

    @router.get("/api/maps/reference/boundaries")
    def boundaries():
        path = root / "boundaries.geojson"
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, "Global boundary package has not been installed")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise HTTPException(413, "Boundary package exceeds supported size")
        return FileResponse(path, media_type="application/geo+json",
                            headers={"Cache-Control": "private, max-age=3600"})

    @router.get("/api/maps/reference/labels")
    def labels():
        path = root / "labels.geojson"
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, "Global reference package has not been installed")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise HTTPException(413, "Reference label package exceeds supported size")
        return FileResponse(path, media_type="application/geo+json",
                            headers={"Cache-Control": "private, max-age=3600"})

    return router
