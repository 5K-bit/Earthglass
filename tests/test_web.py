from fastapi.testclient import TestClient

from earthglass.cache import FeatureCache
from earthglass.layers import registry
from earthglass.providers import ProviderManager
from earthglass.usgs import USGSEarthquakeProvider
from earthglass.web.app import app, create_app

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


def test_feature_api_exposes_normalized_renderer_neutral_payload(tmp_path) -> None:
    payload = {
        "type": "FeatureCollection",
        "metadata": {"generated": 1_767_225_660_000},
        "features": [
            {
                "id": "api-test",
                "geometry": {"type": "Point", "coordinates": [-71.0, 42.0, 5.0]},
                "properties": {
                    "time": 1_767_225_600_000,
                    "updated": 1_767_225_650_000,
                    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/api-test",
                    "title": "M 1.2 - API test",
                    "place": "API test",
                    "mag": 1.2,
                },
            }
        ],
    }
    providers = ProviderManager(registry)
    providers.register(
        USGSEarthquakeProvider(
            cache=FeatureCache(tmp_path), fetcher=lambda *_: payload
        )
    )
    local_client = TestClient(create_app(providers))

    response = local_client.get("/api/layers/earthquakes/features")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert data["metadata"]["source"]["provider"] == "usgs"
    assert data["features"][0]["provenance"]["source_id"] == "api-test"
    assert "cesium" not in str(data).lower()
    assert "leaflet" not in str(data).lower()

    status = local_client.get("/api/providers/status")
    assert status.status_code == 200
    assert status.json()[0]["state"] == "ready"

    refreshed = local_client.post("/api/layers/earthquakes/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["metadata"]["cache"]["status"] == "live"


def test_feature_api_returns_503_when_live_and_cache_are_unavailable(tmp_path) -> None:
    providers = ProviderManager(registry)
    providers.register(
        USGSEarthquakeProvider(
            cache=FeatureCache(tmp_path),
            fetcher=lambda *_: (_ for _ in ()).throw(TimeoutError("offline")),
        )
    )
    local_client = TestClient(create_app(providers))
    response = local_client.get("/api/layers/earthquakes/features")
    assert response.status_code == 503
    assert "no valid cache" in response.json()["detail"]
