"""Read-only local map pack serving; acquisition remains an explicit preparation step."""
import json
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

REQUIRED_ASSET_DIRS = ("fonts", "sprites")
REQUIRED_STYLE_FILES = ("style.json",)


def _read_manifest(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "invalid_manifest", "missing": ["valid manifest.json"]}
    return value if isinstance(value, dict) else {
        "status": "invalid_manifest",
        "missing": ["object-valued manifest.json"],
    }


def _assets_available(root: Path) -> bool:
    return (
        all(
            (root / directory).is_dir() and any((root / directory).iterdir())
            for directory in REQUIRED_ASSET_DIRS
        )
        and all((root / filename).is_file() for filename in REQUIRED_STYLE_FILES)
    )


def _archive_available(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def map_router(root: Path):
    root = root.resolve()
    router = APIRouter()

    @router.get("/api/maps/nyc")
    def status():
        archive = root / "nyc.pmtiles"
        metadata = _read_manifest(root / "manifest.json")
        available = _archive_available(archive)
        return {**metadata, "available": available, "archive_bytes": archive.stat().st_size if available else 0,
            "assets_available": _assets_available(root)}

    @router.get("/maps/nyc/nyc.pmtiles")
    def archive(request: Request):
        path = root / "nyc.pmtiles"
        if not _archive_available(path):
            raise HTTPException(404, "NYC map pack has not been prepared")
        size = path.stat().st_size
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers.get("range", ""))
        if not match:
            raise HTTPException(416, "Use a bounded byte range", headers={"Content-Range": f"bytes */{size}"})
        start, end = map(int, match.groups())
        end = min(end, size - 1)
        if start > end or end - start >= 8 * 1024 * 1024:
            raise HTTPException(416, "Map range is invalid or exceeds 8 MiB", headers={"Content-Range": f"bytes */{size}"})
        with path.open("rb") as handle:
            handle.seek(start)
            content = handle.read(end - start + 1)
        return Response(content, status_code=206, media_type="application/octet-stream", headers={
            "Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}",
            "ETag": f'"{size}-{path.stat().st_mtime_ns}"', "Cache-Control": "private, max-age=3600"})

    @router.get("/maps/nyc/{asset:path}")
    def asset(asset: str):
        candidate = root / asset
        # Inspect the requested path before resolve() erases symlink identity.
        if any(part.is_symlink() for part in (candidate, *candidate.parents)):
            raise HTTPException(404, "Map asset unavailable")
        path = candidate.resolve()
        if not path.is_relative_to(root) or path.suffix not in {".pbf", ".png", ".json"} or not path.is_file():
            raise HTTPException(404, "Map asset unavailable")
        return FileResponse(path)

    return router
