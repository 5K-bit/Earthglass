from datetime import datetime, timezone
from threading import Event
import pytest

from earthglass.spatial.engine import SpatialEngine, default_feeds
from earthglass.spatial.feeds.base import Feed, ProviderSpec
from earthglass.spatial.network import PublicHTTP, ProviderError


def test_default_registry_does_not_require_keys_at_construction():
    def credentials(_):
        raise AssertionError("Construction must not read optional keys")
    feeds = default_feeds(None, credentials)
    assert len({feed.spec.id for feed in feeds}) == len(feeds)
    assert {feed.spec.credential for feed in feeds if feed.spec.credential} == {"firms_map_key","ny511_api_key","mta_bustime_api_key"}
    assert "aisstream" not in {feed.spec.id for feed in feeds}
    assert all(feed.credentials is credentials for feed in feeds if feed.spec.credential)


def test_offline_transport_blocks_before_dns():
    def resolver(*args, **kwargs):
        raise AssertionError("Offline requests must not resolve public DNS")
    http = PublicHTTP(resolver=resolver)
    http.offline = True
    try:
        with pytest.raises(ProviderError) as raised:
            http.bytes("https://example.org/frame.jpg")
        assert raised.value.code == "offline_mode"
    finally:
        http.close()


class LocalFeed(Feed):
    spec = ProviderSpec("local_fixture", "perception", "Local", 5, "Local", "Fixture", local=True)
    source_url = "https://example.org/"
    def __init__(self, http):
        super().__init__(http)
        self.called = Event()
        self.release = Event()
    def fetch(self, viewport, now):
        self.called.set()
        self.release.wait(2)
        return [self.observation(source_id="one", position={"latitude": 1, "longitude": 1}, observed_at=now, received_at=now)]


def test_offline_keeps_local_processing_and_suppresses_remote_jobs(tmp_path):
    http = PublicHTTP()
    local = LocalFeed(http)
    class Remote(LocalFeed):
        spec = ProviderSpec("remote_fixture", "aircraft", "Remote", 5, "Public", "Fixture")
    remote = Remote(http)
    engine = SpatialEngine(tmp_path, feeds=[local, remote], http=http)
    try:
        engine.enable("perception")
        engine.enable("aircraft")
        engine.set_offline(True)
        engine.tick()
        assert local.called.wait(2)
        assert not remote.called.is_set()
        local.release.set()
        engine._entries["local_fixture"]["future"].result(timeout=2)
        assert engine.query()["observations"][0]["entity_id"] == "local_fixture:one"
        status = {p["id"]: p for p in engine.catalog()}
        assert status["local_fixture"]["health"]["state"] == "online"
        assert status["remote_fixture"]["health"]["state"] == "offline"
        engine.set_offline(False)
        engine.tick()
        assert remote.called.wait(2)
    finally:
        local.release.set()
        remote.release.set()
        engine.stop()


def test_switching_offline_discards_late_public_results_and_persists(tmp_path):
    http = PublicHTTP()
    class Remote(LocalFeed):
        spec = ProviderSpec("remote_fixture", "aircraft", "Remote", 5, "Public", "Fixture")
    feed = Remote(http)
    engine = SpatialEngine(tmp_path, feeds=[feed], http=http)
    try:
        engine.enable("aircraft")
        engine.tick()
        assert feed.called.wait(2)
        engine.set_offline(True)
        feed.release.set()
        engine._entries["remote_fixture"]["future"].result(timeout=2)
        assert not engine.query()["observations"]
    finally:
        feed.release.set()
        engine.stop()
    restored = SpatialEngine(tmp_path, feeds=[])
    try:
        assert restored.offline and restored.http.offline
        assert restored.network_status()["access"] == "public_with_optional_free_keys"
    finally:
        restored.stop()


def test_retained_road_catalog_is_available_after_offline_restart(tmp_path):
    from earthglass.spatial.feeds.local_context import TrafficFeed
    now = datetime.now(timezone.utc)
    engine = SpatialEngine(tmp_path)
    value = TrafficFeed(None).observation(source_id="way:1", position={"latitude": 1, "longitude": 1}, observed_at=now, received_at=now, kind="catalog")
    value.provenance.provider = "overpass_roads"
    engine.history.ingest([value])
    engine.stop()
    restarted = SpatialEngine(tmp_path)
    try:
        restarted.set_offline(True)
        restarted.enable("traffic")
        assert restarted.query(layers=["traffic"])["observations"][0]["observed_at"] == value.wire()["observed_at"]
        road = next(p for p in restarted.catalog() if p["id"] == "traffic")
        assert road["health"]["state"] == "stale" and road["health"]["count"] == 1
    finally:
        restarted.stop()
