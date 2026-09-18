"""Read-only V2 projections and bounded on-demand tile cache."""

import math
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .models import utc_now
from .network import ProviderError


def envelope(engine, data, *, layers=None, product=None, extra=None):
    providers = [p for p in engine.catalog() if layers is None or p["layer"] in layers]
    now = utc_now()
    sources = []
    for provider in providers:
        health = provider["health"]
        received = health.get("last_success_at")
        age = (
            max(0, (now - datetime.fromisoformat(received)).total_seconds())
            if received
            else None
        )
        sources.append(
            {
                "provider": provider["id"],
                "product": product or provider["layer"],
                "attribution": provider["attribution"],
                "retrieved_at": received,
                "cache_age_seconds": age,
                "cache": True,
                "status": health["state"],
                "enabled": provider["enabled"],
                "last_attempt": health.get("last_attempt_at"),
            }
        )
    return {
        "schema_version": "2.0",
        "data": data,
        "provenance": sources,
        "offline": engine.offline,
        **(extra or {}),
    }


class TileCache:
    def __init__(self, path, *, quota_bytes=128 * 1024 * 1024):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS tiles(key TEXT PRIMARY KEY,payload BLOB,kind TEXT,accessed REAL)"
        )
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(4)
        self._key_locks = [threading.Lock() for _ in range(64)]
        self.quota_bytes = quota_bytes
        self._closed = False

    def get(self, key):
        with self._lock, self._con:
            row = self._con.execute(
                "SELECT payload,kind FROM tiles WHERE key=?", (key,)
            ).fetchone()
            if row:
                self._con.execute(
                    "UPDATE tiles SET accessed=? WHERE key=?", (time.time(), key)
                )
        return row

    def fetch(self, http, key, url):
        cached = self.get(key)
        if cached:
            return cached[0], cached[1], True
        if http.offline:
            raise ProviderError(
                "offline_tile_missing", "This imagery tile has not been cached locally"
            )
        if not self._slots.acquire(timeout=0.05):
            raise ProviderError(
                "tile_busy", "Tile request capacity reached; retry later"
            )
        lock = self._key_locks[hash(key) % len(self._key_locks)]
        try:
            lock.acquire()
            cached = self.get(key)
            if cached:
                return cached[0], cached[1], True
            body, kind = http.bytes(url, max_bytes=2 * 1024 * 1024)
            if not kind.startswith(("image/png", "image/jpeg")):
                raise ProviderError(
                    "invalid_tile", "Source did not return a supported image"
                )
            with self._lock, self._con:
                self._con.execute(
                    "INSERT OR REPLACE INTO tiles VALUES(?,?,?,?)",
                    (key, body, kind, time.time()),
                )
                while (
                    self._con.execute(
                        "SELECT coalesce(sum(length(payload)),0) FROM tiles"
                    ).fetchone()[0]
                    > self.quota_bytes
                ):
                    self._con.execute(
                        "DELETE FROM tiles WHERE key=(SELECT key FROM tiles ORDER BY accessed LIMIT 1)"
                    )
            return body, kind, False
        finally:
            lock.release()
            self._slots.release()

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._con.close()


def imagery_time(product, requested=None):
    default = product.get("default_time")
    if not default:
        raise ValueError("No imagery time available")

    def instant(value):
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=UTC)
            if len(value) == 10
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )

    desired = instant(requested or default)
    if desired.tzinfo is None:
        raise ValueError("Imagery time needs a UTC offset")
    desired = min(desired, instant(default))
    matches = []
    for interval in product.get("time_ranges", []):
        parts = interval.split("/")
        try:
            start = instant(parts[0])
            end = instant(parts[1]) if len(parts) > 1 else start
            if desired < start:
                continue
            point = min(desired, end)
            if len(parts) == 3:
                step = parts[2]
                seconds = (
                    int(step[2:-1]) * 60
                    if step.startswith("PT") and step.endswith("M")
                    else int(step[1:-1]) * 86400
                    if step.startswith("P") and step.endswith("D")
                    else 86400
                )
                from datetime import timedelta

                point = start + timedelta(
                    seconds=math.floor((point - start).total_seconds() / seconds)
                    * seconds
                )
            matches.append(point)
        except (ValueError, TypeError):
            continue
    if not matches:
        raise ValueError("No frame exists at or before the selected time")
    chosen = max(matches)
    return (
        chosen.strftime("%Y-%m-%d")
        if len(default) == 10
        else chosen.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
