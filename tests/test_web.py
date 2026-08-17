from fastapi.testclient import TestClient

from earthglass.web.app import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "earthglass"}


def test_api_layers_contains_renderer_agnostic_earthquakes() -> None:
    response = client.get("/api/layers")
    assert response.status_code == 200

    data = response.json()
    layer_ids = {layer["id"] for layer in data}
    assert "earthquakes" in layer_ids

    earthquakes = next(layer for layer in data if layer["id"] == "earthquakes")
    assert earthquakes["name"] == "Earthquakes"
    assert earthquakes["category"] == "geology"
    assert earthquakes["geometry"] == "point"
    assert earthquakes["provider"] == "usgs"
    assert "leaflet" not in earthquakes
    assert "cesium" not in earthquakes


def test_api_layer_detail() -> None:
    response = client.get("/api/layers/earthquakes")
    assert response.status_code == 200
    assert response.json()["id"] == "earthquakes"


def test_unknown_layer_returns_404() -> None:
    response = client.get("/api/layers/not-real")
    assert response.status_code == 404


def test_status_identifies_layer_engine() -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["architecture"] == "geospatial-layer-engine"


def test_index_remains_demo_surface() -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "EarthGlass" in body
    assert "Earthquakes" in body
