import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from earthglass.cache import FeatureCache
from earthglass.usgs import USGSEarthquakeProvider


def test_cold_concurrent_requests_share_refresh(tmp_path):
    calls = []
    barrier = threading.Barrier(6)
    def fetch(*args):
        calls.append(1)
        time.sleep(0.1)
        return {"type": "FeatureCollection", "features": []}
    provider = USGSEarthquakeProvider(cache=FeatureCache(tmp_path), fetcher=fetch)
    def read(_):
        barrier.wait()
        return provider.get_features("earthquakes")
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(read, range(6)))
    assert len(calls) == 1
    assert len(results) == 6


def test_cache_write_failure_does_not_discard_fresh_data(tmp_path, monkeypatch):
    cache = FeatureCache(tmp_path)
    monkeypatch.setattr(cache, "save", lambda _: (_ for _ in ()).throw(OSError("full")))
    provider = USGSEarthquakeProvider(cache=cache, fetcher=lambda *_: {"type": "FeatureCollection", "features": []})
    result = provider.get_features("earthquakes")
    assert result.cache["status"] == "live"
    assert provider.status.state == "degraded"
