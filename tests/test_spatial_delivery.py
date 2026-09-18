from datetime import datetime, timezone
from types import SimpleNamespace
from earthglass.spatial.engine import SpatialEngine
from earthglass.spatial.history import SpatialHistory
from earthglass.spatial.models import Observation, Viewport


def observation(ident="one", second=0):
    return Observation(
        entity_id=ident,
        layer="aircraft",
        entity_type="aircraft",
        position={"latitude": 1.0, "longitude": 1.0},
        observed_at=datetime(2026, 9, 10, 0, 0, second, tzinfo=timezone.utc),
        provenance={
            "provider": "fixture",
            "source_id": ident,
            "source_url": "https://example.org/",
            "attribution": "Fixture",
        },
    )


def test_outbox_survives_restart_and_preserves_newer_pending(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = SpatialHistory(path)
    history.ingest([observation()])
    first = history.pending_publications()
    history.ingest([observation(second=1)])
    history.acknowledge_publications(first)
    assert len(history.pending_publications()) == 1
    history.close()
    history = SpatialHistory(path)
    assert history.pending_publications()[0]["observation"]["observed_at"].endswith(
        "01Z"
    )
    history.acknowledge_publications(history.pending_publications())
    assert history.publication_status()["pending"] == 0
    history.close()


def test_failed_delivery_is_retried_without_new_observation(tmp_path):
    calls = []

    def publish(changes):
        calls.append(changes)
        if len(calls) == 1:
            raise OSError("offline")

    engine = SpatialEngine(tmp_path, on_observations=publish, feeds=[])
    engine.history.ingest([observation()])
    engine.flush_publications()
    assert engine.delivery_error == "OSError"
    assert engine.history.publication_status()["pending"] == 1
    engine._next_delivery = 0
    engine.flush_publications()
    assert len(calls) == 2 and engine.history.publication_status()["pending"] == 0
    engine.stop()


def test_global_viewport_center_and_bounded_provider():
    from earthglass.spatial.feeds.base import Feed
    from earthglass.spatial.network import ProviderError
    import pytest

    viewport = Viewport(west=-180, south=-90, east=180, north=90)
    assert viewport.center == (0, 0)
    with pytest.raises(ProviderError):
        Feed(None).bounded(viewport)


def test_naive_source_time_rejected():
    from earthglass.spatial.feeds.base import timestamp
    import pytest

    with pytest.raises(ValueError):
        timestamp("2026-09-10T00:00:00")


def test_navigation_retries_zoom_gate_without_bypassing_upstream_backoff(tmp_path):
    from earthglass.spatial.feeds.local_context import InfrastructureFeed
    from earthglass.spatial.network import ProviderError
    import time
    feed = InfrastructureFeed(None)
    engine = SpatialEngine(tmp_path, feeds=[feed])
    engine.enable("infrastructure")
    entry = engine._entries["overpass"]
    engine._failed(entry, entry["generation"], ProviderError("zoom_required", "Zoom in"))
    assert entry["next"] > time.monotonic() + 3500
    engine.set_viewport({"west": -74.1, "east": -74, "south": 40.7, "north": 40.8})
    assert entry["next"] < time.monotonic()
    engine._failed(entry, entry["generation"], ProviderError("quota_exceeded", "Wait"))
    deadline = entry["next"]
    engine.set_viewport({"west": -74.2, "east": -74, "south": 40.7, "north": 40.8})
    assert entry["next"] == deadline
    engine.stop()


def test_navigation_refreshes_slow_catalog_with_bounded_requests(tmp_path):
    from earthglass.spatial.feeds.local_context import InfrastructureFeed
    import time
    engine = SpatialEngine(tmp_path, feeds=[InfrastructureFeed(None)])
    engine.enable("infrastructure")
    entry = engine._entries["overpass"]
    entry["last_started"] = time.monotonic()
    engine._accept(entry, entry["generation"], [])
    engine.set_viewport({"west": -74.1, "east": -74, "south": 40.7, "north": 40.8})
    assert 28 < entry["next"] - time.monotonic() <= 30
    # A prior in-flight response must not restore the one-hour delay.
    engine._accept(entry, entry["generation"], [])
    assert entry["next"] - time.monotonic() <= 30
    engine.stop()
