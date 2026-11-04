from datetime import datetime, timezone

import pytest

from earthglass.cache import FeatureCache
from earthglass.nws import NWSAlertsProvider, NWS_ALERTS_URL
from earthglass.providers import NormalizedFeature, ProviderUnavailable

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-74.2, 40.6], [-73.8, 40.6], [-73.8, 40.9], [-74.2, 40.9], [-74.2, 40.6]]],
}


def alert(alert_id="urn:oid:1", *, status="Actual", geometry=POLYGON, expires="2026-11-04T18:00:00-00:00", ends=None):
    return {
        "id": f"https://api.weather.gov/alerts/{alert_id}",
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "status": status, "event": "Flood Warning", "severity": "Severe",
            "urgency": "Expected", "certainty": "Likely", "headline": "Flood Warning issued",
            "areaDesc": "Bronx, NY", "messageType": "Alert", "senderName": "NWS New York NY",
            "sent": "2026-11-04T11:00:00-00:00", "effective": "2026-11-04T11:00:00-00:00",
            "onset": None, "expires": expires, "ends": ends,
            "affectedZones": ["https://api.weather.gov/zones/forecast/NYZ072"],
        },
    }


def payload(*features):
    return {"type": "FeatureCollection", "updated": "2026-11-04T11:59:00+00:00", "features": list(features)}


def make(tmp_path, body, clock=lambda: NOW):
    return NWSAlertsProvider(cache=FeatureCache(tmp_path), fetcher=lambda url, timeout: body, clock=clock)


def test_normalizes_polygon_alert_with_provenance(tmp_path):
    provider = make(tmp_path, payload(alert()))
    collection = provider.refresh("weather-alerts")
    feature = collection.features[0]
    assert feature.geometry["type"] == "Polygon"
    assert feature.properties["kind"] == "weather_alert"
    assert feature.properties["event"] == "Flood Warning"
    assert feature.properties["expires"] == "2026-11-04T18:00:00Z"
    assert feature.properties["located"] is True
    assert feature.provenance["source_url"].startswith("https://api.weather.gov/alerts/")
    assert collection.source.provider == "nws"
    assert collection.source.source_url == NWS_ALERTS_URL
    assert FeatureCache(tmp_path).load("weather-alerts") == collection


def test_test_and_exercise_alerts_are_never_shown(tmp_path):
    body = payload(alert("a", status="Test"), alert("b", status="Exercise"), alert("c"))
    collection = make(tmp_path, body).refresh("weather-alerts")
    assert [f.provenance["source_id"].rsplit("/", 1)[-1] for f in collection.features] == ["c"]


def test_zone_only_alert_is_kept_not_dropped(tmp_path):
    collection = make(tmp_path, payload(alert(geometry=None))).refresh("weather-alerts")
    feature = collection.features[0]
    assert feature.geometry is None
    assert feature.properties["located"] is False
    assert feature.properties["affected_zones"]


def test_expired_alerts_are_removed_even_from_cache(tmp_path):
    clock = {"now": NOW}
    provider = make(tmp_path, payload(alert()), clock=lambda: clock["now"])
    provider.refresh("weather-alerts")
    clock["now"] = datetime(2026, 11, 4, 12, 1, tzinfo=timezone.utc)
    assert len(provider.get_features("weather-alerts").features) == 1
    clock["now"] = datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc)
    served = provider.get_features  # cache is stale now; upstream failing must not resurrect it
    provider.fetcher = lambda *_: (_ for _ in ()).throw(RuntimeError("down"))
    result = served("weather-alerts")
    assert result.features == ()
    assert result.cache["stale"] is True


def test_ends_takes_precedence_over_expires(tmp_path):
    body = payload(alert(expires="2026-11-04T23:00:00-00:00", ends="2026-11-04T11:30:00-00:00"))
    assert make(tmp_path, body).refresh("weather-alerts").features == ()


def test_outage_without_cache_is_explicit(tmp_path):
    def down(url, timeout):
        raise RuntimeError("down")
    provider = NWSAlertsProvider(cache=FeatureCache(tmp_path), fetcher=down, clock=lambda: NOW)
    with pytest.raises(ProviderUnavailable):
        provider.refresh("weather-alerts")
    assert provider.status.state == "unavailable"


def test_outage_with_cache_marks_data_stale(tmp_path):
    provider = make(tmp_path, payload(alert()))
    provider.refresh("weather-alerts")
    provider.fetcher = lambda *_: (_ for _ in ()).throw(RuntimeError("down"))
    result = provider.refresh("weather-alerts")
    assert result.cache["stale"] is True
    assert provider.status.state == "degraded"


def test_rejects_bad_geometry_and_unknown_layer(tmp_path):
    open_ring = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}
    with pytest.raises(ValueError):
        NormalizedFeature(id="x", geometry=open_ring, properties={"observed_at": "2026-01-01T00:00:00Z"},
                          provenance={"provider": "p", "source_id": "1", "source_url": "u", "retrieved_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(KeyError):
        make(tmp_path, payload()).refresh("earthquakes")


def test_alerts_layer_is_served_through_the_api(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from earthglass.layers import registry
    from earthglass.nws import NWSAlertsProvider
    from earthglass.providers import ProviderManager
    from earthglass.web.app import create_app

    body = {"type": "FeatureCollection", "features": [{
        "id": "https://api.weather.gov/alerts/urn:oid:9", "type": "Feature", "geometry": None,
        "properties": {"status": "Actual", "event": "Tornado Warning", "sent": "2999-01-01T00:00:00+00:00",
                       "expires": "2999-01-01T01:00:00+00:00", "affectedZones": []}}]}
    manager = ProviderManager(registry)
    manager.register(NWSAlertsProvider(cache=FeatureCache(tmp_path), fetcher=lambda *_: body))
    api = TestClient(create_app(manager))
    data = api.get("/api/layers/weather-alerts/features").json()
    assert data["metadata"]["source"]["provider"] == "nws"
    assert data["features"][0]["properties"]["event"] == "Tornado Warning"
    assert data["features"][0]["geometry"] is None


def test_point_alerts_query_one_location_and_cache_it(tmp_path):
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        return payload(alert(geometry=None))

    provider = NWSAlertsProvider(cache=FeatureCache(tmp_path), fetcher=fetch, clock=lambda: NOW)
    first = provider.get_point_alerts(40.713, -74.006)
    provider.get_point_alerts(40.7131, -74.0059)  # rounds to the same point: no new request
    assert len(calls) == 1 and "point=40.71,-74.01" in calls[0]
    assert first.features[0].properties["located"] is False
    assert first.source.source_url == calls[0]


def test_point_alerts_stale_on_outage_and_503_over_http(tmp_path):
    from fastapi.testclient import TestClient

    from earthglass.layers import registry
    from earthglass.providers import ProviderManager
    from earthglass.web.app import create_app

    clock = {"now": NOW}
    state = {"down": False}

    def fetch(url, timeout):
        if state["down"]:
            raise RuntimeError("down")
        return payload(alert())

    provider = NWSAlertsProvider(cache=FeatureCache(tmp_path), fetcher=fetch, clock=lambda: clock["now"])
    manager = ProviderManager(registry)
    manager.register(provider)
    api = TestClient(create_app(manager))
    assert api.get("/api/weather/alerts/point", params={"lat": 40.7, "lon": -74.0}).status_code == 200
    state["down"] = True
    clock["now"] = datetime(2026, 11, 4, 12, 10, tzinfo=timezone.utc)
    stale = api.get("/api/weather/alerts/point", params={"lat": 40.7, "lon": -74.0}).json()
    assert stale["metadata"]["cache"]["stale"] is True
    assert api.get("/api/weather/alerts/point", params={"lat": 25.7, "lon": -80.2}).status_code == 503
    assert api.get("/api/weather/alerts/point", params={"lat": 99, "lon": 0}).status_code == 422
