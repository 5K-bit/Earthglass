from datetime import datetime, timedelta, timezone

import pytest

from earthglass.cache import FeatureCache
from earthglass.providers import NormalizedFeature, ProviderUnavailable
from earthglass.usgs import USGSEarthquakeProvider, USGS_EARTHQUAKES_URL


def usgs_payload() -> dict:
    return {
        "type": "FeatureCollection",
        "metadata": {"generated": 1_767_225_660_000},
        "features": [
            {
                "type": "Feature",
                "id": "test123",
                "geometry": {"type": "Point", "coordinates": [-122.1, 37.4, 8.2]},
                "properties": {
                    "time": 1_767_225_600_000,
                    "updated": 1_767_225_650_000,
                    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/test123",
                    "detail": "https://earthquake.usgs.gov/fdsnws/event/1/query?eventid=test123",
                    "title": "M 2.4 - Test location",
                    "place": "Test location",
                    "mag": 2.4,
                    "magType": "ml",
                    "status": "reviewed",
                    "sig": 89,
                },
            }
        ],
    }


def test_live_refresh_normalizes_validates_and_persists(tmp_path) -> None:
    now = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
    calls = []

    def fetcher(url: str, timeout: float) -> dict:
        calls.append((url, timeout))
        return usgs_payload()

    cache = FeatureCache(tmp_path)
    provider = USGSEarthquakeProvider(cache=cache, fetcher=fetcher, clock=lambda: now)
    collection = provider.refresh("earthquakes")

    assert calls == [(USGS_EARTHQUAKES_URL, 10.0)]
    assert collection.cache == {"status": "live", "stale": False}
    assert collection.source.provider == "usgs"
    assert collection.source.attribution == "U.S. Geological Survey (USGS)"
    assert collection.source.upstream_generated_at == "2026-01-01T00:01:00Z"
    feature = collection.features[0]
    assert feature.id == "usgs:test123"
    assert feature.geometry["coordinates"] == [-122.1, 37.4, 8.2]
    assert feature.properties["kind"] == "earthquake"
    assert feature.properties["observed_at"] == "2026-01-01T00:00:00Z"
    assert feature.provenance["source_id"] == "test123"
    assert cache.load("earthquakes") == collection
    assert provider.status.state == "ready"
    assert provider.status.cache_available is True
    assert provider.status.feature_count == 1


def test_fresh_disk_cache_avoids_network(tmp_path) -> None:
    now = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
    first = USGSEarthquakeProvider(
        cache=FeatureCache(tmp_path), fetcher=lambda *_: usgs_payload(), clock=lambda: now
    )
    first.refresh("earthquakes")

    def should_not_fetch(*_args):
        raise AssertionError("fresh cache should prevent a network request")

    second = USGSEarthquakeProvider(
        cache=FeatureCache(tmp_path), fetcher=should_not_fetch, clock=lambda: now
    )
    assert second.status.cache_available is True
    assert second.status.feature_count == 1
    collection = second.get_features("earthquakes")

    assert collection.cache["status"] == "cache"
    assert collection.cache["stale"] is False
    assert second.status.state == "ready"
    assert second.status.serving_cache is True


def test_failed_refresh_serves_explicitly_stale_cache(tmp_path) -> None:
    initial = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
    current = [initial]
    provider = USGSEarthquakeProvider(
        cache=FeatureCache(tmp_path),
        fetcher=lambda *_: usgs_payload(),
        clock=lambda: current[0],
    )
    provider.refresh("earthquakes")
    current[0] += timedelta(minutes=10)

    def unavailable(*_args):
        raise TimeoutError("upstream timed out")

    provider.fetcher = unavailable
    collection = provider.get_features("earthquakes")

    assert collection.cache["status"] == "cache"
    assert collection.cache["stale"] is True
    assert collection.cache["age_seconds"] == 600
    assert provider.status.state == "degraded"
    assert provider.status.cache_stale is True
    assert "upstream timed out" in provider.status.last_error


def test_failed_refresh_without_cache_is_unavailable(tmp_path) -> None:
    def unavailable(*_args):
        raise TimeoutError("offline")

    provider = USGSEarthquakeProvider(
        cache=FeatureCache(tmp_path), fetcher=unavailable
    )
    with pytest.raises(ProviderUnavailable, match="no valid cache"):
        provider.refresh("earthquakes")
    assert provider.status.state == "unavailable"


def test_normalized_feature_rejects_invalid_coordinates() -> None:
    with pytest.raises(ValueError, match="geographic bounds"):
        NormalizedFeature(
            id="bad",
            geometry={"type": "Point", "coordinates": [181, 20]},
            properties={"observed_at": "2026-01-01T00:00:00Z"},
            provenance={
                "provider": "fixture",
                "source_id": "bad",
                "source_url": "https://example.test/bad",
                "retrieved_at": "2026-01-01T00:00:00Z",
            },
        )


def test_corrupt_cache_is_ignored(tmp_path) -> None:
    cache = FeatureCache(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    cache.path_for("earthquakes").write_text("not json", encoding="utf-8")
    assert cache.load("earthquakes") is None


def test_status_reports_aged_cache_as_stale_without_a_request(tmp_path) -> None:
    """Regression: status used to say cache_stale=False for a 3-hour-old cache
    until some request happened to trigger a refresh."""
    current = [datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)]
    provider = USGSEarthquakeProvider(
        cache=FeatureCache(tmp_path),
        fetcher=lambda *_: usgs_payload(),
        clock=lambda: current[0],
    )
    provider.refresh("earthquakes")
    assert provider.status.cache_stale is False
    current[0] += timedelta(hours=3)
    assert provider.status.cache_stale is True
    assert provider.status.cache_age_seconds == 10800
