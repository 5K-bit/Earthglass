from fastapi import FastAPI
from fastapi.testclient import TestClient

from earthglass.spatial.reference_maps import reference_router


def test_missing_package_and_installed_package(tmp_path):
    app = FastAPI()
    app.include_router(reference_router(tmp_path))
    client = TestClient(app)
    assert client.get("/api/maps/reference/labels").status_code == 404
    (tmp_path / "labels.geojson").write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    response = client.get("/api/maps/reference/labels")
    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"
    assert response.headers["cache-control"].startswith("private")


def test_boundary_package_is_local_and_optional(tmp_path):
    app = FastAPI()
    app.include_router(reference_router(tmp_path))
    client = TestClient(app)
    assert client.get("/api/maps/reference/boundaries").status_code == 404
    (tmp_path / "boundaries.geojson").write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    response = client.get("/api/maps/reference/boundaries")
    assert response.status_code == 200
    assert response.json()["features"] == []
