from fastapi import FastAPI
from fastapi.testclient import TestClient
from earthglass.spatial.local_maps import map_router


def test_local_archive_ranges_and_missing_pack(tmp_path):
    app = FastAPI()
    app.include_router(map_router(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/maps/nyc").json()["available"] is False
        assert client.get("/maps/nyc/nyc.pmtiles", headers={"Range": "bytes=0-9"}).status_code == 404
        (tmp_path / "nyc.pmtiles").write_bytes(b"0123456789")
        response = client.get("/maps/nyc/nyc.pmtiles", headers={"Range": "bytes=2-5"})
        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-range"] == "bytes 2-5/10"
        assert client.get("/maps/nyc/nyc.pmtiles").status_code == 416
        assert client.get("/maps/nyc/nyc.pmtiles", headers={"Range": "bytes=20-30"}).status_code == 416
        assert client.get("/maps/nyc/no-secret.txt").status_code == 404


def test_map_status_rejects_invalid_manifest_and_requires_nonempty_assets(tmp_path):
    app = FastAPI()
    app.include_router(map_router(tmp_path))
    (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")
    (tmp_path / "nyc.pmtiles").write_bytes(b"tiles")
    (tmp_path / "fonts").mkdir()
    (tmp_path / "sprites").mkdir()
    with TestClient(app) as client:
        status = client.get("/api/maps/nyc").json()
        assert status["status"] == "invalid_manifest"
        assert status["available"] is True
        assert status["assets_available"] is False

        (tmp_path / "fonts" / "font.pbf").write_bytes(b"font")
        (tmp_path / "sprites" / "sprite.png").write_bytes(b"sprite")
        (tmp_path / "style.json").write_text("{}", encoding="utf-8")
        assert client.get("/api/maps/nyc").json()["assets_available"] is True


def test_map_asset_symlinks_are_not_served(tmp_path):
    app = FastAPI()
    app.include_router(map_router(tmp_path))
    target = tmp_path / "secret.json"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "style.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return
    with TestClient(app) as client:
        assert client.get("/maps/nyc/style.json").status_code == 404


def test_symlinked_archive_is_not_available(tmp_path):
    app = FastAPI()
    app.include_router(map_router(tmp_path))
    target = tmp_path / "outside.pmtiles"
    target.write_bytes(b"tiles")
    archive = tmp_path / "nyc.pmtiles"
    try:
        archive.symlink_to(target)
    except (OSError, NotImplementedError):
        return
    with TestClient(app) as client:
        status = client.get("/api/maps/nyc").json()
        assert status["available"] is False
        assert client.get("/maps/nyc/nyc.pmtiles", headers={"Range": "bytes=0-4"}).status_code == 404
