"""Replay EarthGlass's fresh / stale / unavailable behaviour on a fixed dataset.

No network is used. The real FastAPI app and the real USGSEarthquakeProvider
and FeatureCache run behind a real HTTP server (uvicorn on 127.0.0.1). Only the
upstream fetcher and the clock are replaced, so each scenario is repeatable.

    python tools/freshness_demo.py [--out docs/demo/freshness-transcript.md]
"""

from __future__ import annotations

import argparse
import json
import socket
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import uvicorn

from earthglass.cache import FeatureCache
from earthglass.layers import registry
from earthglass.providers import ProviderManager
from earthglass.usgs import USGSEarthquakeProvider
from earthglass.web.app import create_app

FIXTURE = Path(__file__).resolve().parent.parent / "docs" / "demo" / "usgs-fixture.json"
T0 = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)


class Upstream:
    """Fake USGS: serves the fixture, or fails the way a dead network would."""

    def __init__(self) -> None:
        self.up = True
        self.calls = 0

    def __call__(self, url: str, timeout: float) -> dict:
        self.calls += 1
        if not self.up:
            raise TimeoutError("upstream timed out (simulated)")
        return json.loads(FIXTURE.read_text(encoding="utf-8"))


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class Server:
    def __init__(self, cache_dir: Path, upstream: Upstream, clock: Clock) -> None:
        self.provider = USGSEarthquakeProvider(
            cache=FeatureCache(cache_dir), fetcher=upstream, clock=clock
        )
        manager = ProviderManager(registry)
        manager.register(self.provider)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = uvicorn.Config(create_app(manager), host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                httpx.get(self.base + "/health", timeout=1)
                return
            except httpx.HTTPError:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def observe(base: str, label: str, rows: list[dict], *, method: str = "GET") -> None:
    url = base + ("/api/layers/earthquakes/refresh" if method == "POST" else "/api/layers/earthquakes/features")
    response = httpx.request(method, url, timeout=10)
    status = httpx.get(base + "/api/providers/status", timeout=10).json()[0]
    row = {"step": label, "http": response.status_code}
    if response.status_code == 200:
        body = response.json()
        meta = body["metadata"]
        row.update(
            features=len(body["features"]),
            cache_status=meta["cache"]["status"],
            stale=meta["cache"]["stale"],
            age_seconds=meta["cache"].get("age_seconds"),
            retrieved_at=meta["source"]["retrieved_at"],
        )
    else:
        row.update(features=None, cache_status=None, stale=None, age_seconds=None,
                   retrieved_at=None, detail=response.json().get("detail"))
    row.update(
        provider_state=status["state"],
        serving_cache=status["serving_cache"],
        last_error=status["last_error"],
    )
    rows.append(row)


def run() -> list[dict]:
    rows: list[dict] = []
    upstream, clock = Upstream(), Clock()
    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = Path(tmp) / "cache"

        s = Server(cache_dir, upstream, clock)
        observe(s.base, "1 cold start, upstream up", rows)
        clock.now = T0 + timedelta(minutes=2)
        observe(s.base, "2 +2 min, inside 5 min interval", rows)
        clock.now = T0 + timedelta(minutes=10)
        upstream.up = False
        observe(s.base, "3 +10 min, upstream down", rows)
        observe(s.base, "4 manual refresh while upstream down", rows, method="POST")
        s.stop()

        s = Server(cache_dir, upstream, clock)
        observe(s.base, "5 process restarted, upstream still down (disk cache)", rows)
        upstream.up = True
        observe(s.base, "6 upstream recovered", rows)
        s.stop()

        (cache_dir / "earthquakes.json").write_text("not json", encoding="utf-8")
        upstream.up = False
        s = Server(cache_dir, upstream, clock)
        observe(s.base, "7 corrupt cache file, upstream down", rows)
        s.stop()

        s = Server(Path(tmp) / "empty", upstream, clock)
        observe(s.base, "8 no cache at all, upstream down", rows)
        s.stop()
    return rows


def render(rows: list[dict]) -> str:
    head = "| Step | HTTP | cache.status | stale | age (s) | features | provider state | serving cache |\n|---|---|---|---|---|---|---|---|\n"
    body = "".join(
        f"| {r['step']} | {r['http']} | {r['cache_status']} | {r['stale']} | {r['age_seconds']} | {r['features']} | {r['provider_state']} | {r['serving_cache']} |\n"
        for r in rows
    )
    errs = "".join(
        f"- Step {r['step'].split()[0]}: `{r.get('detail') or r['last_error']}`\n"
        for r in rows if r.get("detail") or r["last_error"]
    )
    return head + body + "\nErrors reported:\n\n" + errs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = run()
    text = render(rows)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
