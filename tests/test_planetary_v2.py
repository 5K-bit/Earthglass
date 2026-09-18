from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from earthglass.spatial.engine import SpatialEngine
from earthglass.spatial.models import Viewport
from earthglass.spatial.geometry import normalize_geometry
from earthglass.spatial.feeds.planetary import (
    NWSAlertFeed,
    EonetFeed,
    AviationWeatherFeed,
)
from earthglass.spatial.feeds.documents import SpaceWeatherFeed
from earthglass.spatial.feeds.orbits import OrbitalFeed
from earthglass.spatial.feeds.environment import WeatherFeed
from earthglass.spatial.products import TileCache, imagery_time
from earthglass.spatial.v2_api import build_v2_router
from earthglass.spatial.network import ProviderError
from earthglass.spatial.temporal import project_weather

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
WORLD = Viewport(west=-180, south=-90, east=180, north=90)
AREA = Viewport(west=-75, south=40, east=-73, north=42)


class HTTP:
    offline = False

    def __init__(self, data):
        self.data = data
        self.calls = []

    def json(self, url, **kw):
        self.calls.append(url)
        value = self.data(url, kw) if callable(self.data) else self.data
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        pass


def test_geometry_bounds_include_unsampled_extrema_and_reject_invalid():
    points = [[i / 10, 1] for i in range(100)]
    points[41] = [60, 8]
    geometry, _, bounds = normalize_geometry(
        {"type": "LineString", "coordinates": points}, max_points=10
    )
    assert (
        len(geometry["coordinates"]) <= 11 and geometry["coordinates"][-1] == points[-1]
    )
    assert bounds["east"] == 60 and bounds["north"] == 8
    points[41] = [float("nan"), 1]
    with pytest.raises(ValueError):
        normalize_geometry({"type": "LineString", "coordinates": points}, max_points=10)


def test_alert_zone_polygon_expiry_and_missing_geometry(tmp_path):
    alert = {
        "id": "https://api.weather.gov/alerts/fixture",
        "geometry": None,
        "properties": {
            "status": "Actual",
            "sent": NOW.isoformat(),
            "expires": (NOW + timedelta(hours=2)).isoformat(),
            "event": "Flood",
            "severity": "Severe",
            "affectedZones": ["https://api.weather.gov/zones/county/NYC061"],
        },
    }
    polygon = {
        "type": "Polygon",
        "coordinates": [[[-76, 39], [-72, 39], [-72, 43], [-76, 43], [-76, 39]]],
    }
    http = HTTP(
        lambda url, _: (
            {"features": [alert]} if url.endswith("/alerts") else {"geometry": polygon}
        )
    )
    feed = NWSAlertFeed(http)
    feed.configure_cache(tmp_path)
    values = feed.fetch(AREA, NOW)
    assert len(values) == 1 and values[0].properties["zone_derived"]
    assert values[0].properties["severity"] == "Severe"
    assert feed.fetch(AREA, NOW + timedelta(hours=3)) == []
    assert (tmp_path / "nws-zones.json").exists()


@pytest.mark.parametrize("product", ["metar", "taf", "sigmet", "gairmet", "pirep"])
def test_all_aviation_products_keep_geometry_and_source_time(product):
    row = {
        "type": "Feature",
        "id": "station-a",
        "geometry": {"type": "Point", "coordinates": [-74, 41]},
        "properties": {
            "id": "KTEST",
            "obsTime": NOW.isoformat(),
            "rawOb": "Fixture weather",
        },
    }
    feed = AviationWeatherFeed(HTTP({"features": [row]}), product=product)
    values = feed.fetch(AREA, NOW)
    assert values and values[0].observed_at == NOW
    assert values[0].properties["source_fields"]["id"] == "KTEST"
    assert values[0].measurement_kind == (
        "predicted" if product in {"taf", "gairmet"} else "observed"
    )


def test_eonet_preserves_native_geometry_and_categories():
    event = {
        "id": "EONET_fixture",
        "title": "Fixture volcano",
        "categories": [{"id": "volcanoes", "title": "Volcanoes"}],
        "geometry": [
            {"date": NOW.isoformat(), "type": "Point", "coordinates": [-74, 41]}
        ],
    }
    value = EonetFeed(HTTP({"events": [event]})).fetch(AREA, NOW)[0]
    assert value.properties["categories"][0]["id"] == "volcanoes"
    assert value.position.longitude == -74


def test_imagery_nearest_earlier_frame_no_future_or_missing_fallback():
    product = {
        "default_time": "2026-09-11",
        "time_ranges": ["2026-09-01/2026-09-11/P2D"],
    }
    assert imagery_time(product, "2026-09-10T12:00:00Z") == "2026-09-09"
    assert imagery_time(product, "2027-01-01T00:00:00Z") == "2026-09-11"
    with pytest.raises(ValueError):
        imagery_time(product, "2020-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        imagery_time(product, "2026-09-10T12:00:00")


def test_tile_cache_reuses_refresh_and_offline_never_fetches(tmp_path):
    class Tiles:
        offline = False
        calls = 0

        def bytes(self, *args, **kwargs):
            import time

            self.calls += 1
            time.sleep(0.02)
            return b"fixture-png", "image/png"

    http = Tiles()
    cache = TileCache(tmp_path / "tiles.sqlite3", quota_bytes=100)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(
                pool.map(
                    lambda _: cache.fetch(http, "one", "https://example.org/tile"),
                    range(4),
                )
            )
        assert http.calls == 1 and len(values) == 4
        http.offline = True
        assert cache.fetch(http, "one", "https://example.org/tile")[2]
        with pytest.raises(ProviderError):
            cache.fetch(http, "missing", "https://example.org/tile")
        assert http.calls == 1
    finally:
        cache.close()
        cache.close()


def test_space_weather_retains_product_times_and_never_emits_fake_positions(tmp_path):
    http = HTTP(
        lambda url, _: (
            [{"time_tag": NOW.isoformat(), "active": True, "proton_speed": 410}]
            if "/rtsw/" in url
            else [{"time_tag": NOW.isoformat(), "Kp": 4}]
        )
    )
    feed = SpaceWeatherFeed(http)
    feed.configure_cache(tmp_path)
    assert feed.fetch(WORLD, NOW) == []
    doc = feed.document()
    assert doc["data"]["solar_wind"]["records"][0]["speed"] == 410
    http.data = ProviderError("unavailable", "fixture")
    with pytest.raises(ProviderError):
        feed.fetch(WORLD, NOW + timedelta(hours=1))
    assert feed.document()["retrieved_at"] == doc["retrieved_at"]


def omm_record():
    return {
        "OBJECT_NAME": "Fixture station",
        "OBJECT_ID": "1998-067A",
        "EPOCH": "2026-09-11T12:00:00",
        "MEAN_MOTION": 15.5,
        "ECCENTRICITY": 0.0004,
        "INCLINATION": 51.64,
        "RA_OF_ASC_NODE": 10,
        "ARG_OF_PERICENTER": 30,
        "MEAN_ANOMALY": 40,
        "EPHEMERIS_TYPE": 0,
        "CLASSIFICATION_TYPE": "U",
        "NORAD_CAT_ID": 25544,
        "ELEMENT_SET_NO": 999,
        "REV_AT_EPOCH": 1234,
        "BSTAR": 0.0001,
        "MEAN_MOTION_DOT": 0.00001,
        "MEAN_MOTION_DDOT": 0,
    }


def test_orbits_cached_restart_offline_and_epoch_limit(tmp_path):
    http = HTTP([omm_record()])
    feed = OrbitalFeed(http)
    feed.configure_cache(tmp_path)
    values = feed.fetch(WORLD, NOW)
    assert (
        len(values) == 1
        and values[0].measurement_kind == "predicted"
        and len(values[0].properties["prediction_samples"]) == 3
    )
    http.offline = True
    restored = OrbitalFeed(http)
    restored.configure_cache(tmp_path)
    newer = restored.fetch(WORLD, NOW + timedelta(hours=8))
    assert newer and len(http.calls) == 1
    assert restored.project(NOW + timedelta(days=8)) == []
    assert newer[0].position != values[0].position


def test_forecast_selection_keeps_explicit_units_and_nulls():
    feed = WeatherFeed(
        HTTP(
            {
                "latitude": 41,
                "longitude": -74,
                "current": {"time": "2026-09-11T12:00", "temperature_2m": 20},
                "hourly": {
                    "time": ["2026-09-11T13:00"],
                    "temperature_2m": [21],
                    "surface_pressure": [1001],
                },
            }
        )
    )
    value = feed.fetch(AREA, NOW)[0].wire()
    projected = project_weather(value, NOW + timedelta(hours=1))
    assert projected["properties"]["temperature_c"] == 21
    assert projected["properties"]["pressure_pa"] == 100100
    assert projected["properties"]["precipitation_mm"] is None
    assert project_weather(value, NOW + timedelta(days=3)) is None


def test_v2_routes_offline_envelopes_and_validation(tmp_path):
    engine = SpatialEngine(tmp_path / "public", feeds=[])
    engine.set_offline(True)
    tiles = TileCache(tmp_path / "tiles.sqlite3")
    app = FastAPI()
    app.include_router(build_v2_router(engine, tiles))
    try:
        with TestClient(app) as api:
            paths = [
                "system/providers",
                "aircraft",
                "seismic/events",
                "fires",
                "alerts/weather",
                "events",
                "events/categories",
                "aviation/metar",
                "aviation/taf",
                "aviation/sigmet",
                "aviation/pirep",
                "aviation/gairmet",
                "weather/status",
                "weather/layers",
                "weather/temperature",
                "weather/wind",
                "weather/precipitation",
                "weather/pressure",
                "weather/clouds",
                "imagery/catalog",
                "imagery/layers",
                "imagery/status",
                "orbits/groups",
                "orbits/objects",
                "space-weather/current",
                "space-weather/alerts",
                "space-weather/history",
                "mobility/status",
                "mobility/providers",
                "mobility/traffic",
                "mobility/traffic/incidents",
                "mobility/cameras",
                "mobility/transit/vehicles",
                "mobility/transit/routes",
                "mobility/transit/alerts",
                "mobility/transit/imports",
            ]
            for path in paths:
                response = api.get("/api/v2/" + path)
                assert response.status_code == 200, (path, response.text)
                assert (
                    response.json()["schema_version"] == "2.0"
                    and response.json()["offline"]
                )
            assert api.get("/api/v2/aircraft?west=0").status_code == 422
            assert (
                api.get("/api/v2/orbits/objects?at=2026-09-11T12:00:00").status_code
                == 422
            )
            assert (
                api.get("/api/v2/orbits/25544/track?minutes=10000").status_code == 422
            )
    finally:
        tiles.close()
        engine.stop()


def test_noaa_reported_geomagnetic_scale_and_sigmet_partial_failure(tmp_path):
    http = HTTP(
        lambda url, _: (
            {
                "0": {
                    "DateStamp": "2026-09-11",
                    "TimeStamp": "12:00:00",
                    "G": {"Scale": "2", "Text": "moderate"},
                }
            }
            if url.endswith("noaa-scales.json")
            else []
        )
    )
    feed = SpaceWeatherFeed(http)
    feed.configure_cache(tmp_path)
    feed.fetch(WORLD, NOW)
    storm = feed.document()["data"]["geomagnetic"]["records"][0]
    assert storm["scale"] == 2 and storm["time_tag"] == NOW.isoformat().replace(
        "+00:00", "Z"
    )
    row = {
        "id": "fixture",
        "geometry": {"type": "Point", "coordinates": [-74, 41]},
        "properties": {"obsTime": NOW.isoformat()},
    }
    awc = AviationWeatherFeed(
        HTTP(
            lambda url, _: (
                ProviderError("unavailable", "fixture")
                if url.endswith("/isigmet")
                else {"features": [row]}
            )
        ),
        product="sigmet",
    )
    assert len(awc.fetch(AREA, NOW)) == 1
    assert awc.rejected == 1 and "isigmet" in awc.status_message
