"""USGS earthquake provider adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import httpx

from earthglass.cache import FeatureCache
from earthglass.providers import (
    FeatureCollection,
    NormalizedFeature,
    ProviderStatus,
    ProviderUnavailable,
    SourceMetadata,
    isoformat,
    parse_timestamp,
    utc_now,
)

USGS_EARTHQUAKES_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)
USGS_ATTRIBUTION = "U.S. Geological Survey (USGS)"
USGS_LICENSE_URL = "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits"

JsonFetcher = Callable[[str, float], dict[str, Any]]


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def timestamp_from_millis(value: Any) -> str:
    if not isinstance(value, (int, float)):
        raise ValueError("USGS timestamp must be milliseconds since epoch")
    return isoformat(datetime.fromtimestamp(value / 1000, timezone.utc))


class USGSEarthquakeProvider:
    name = "usgs"

    def __init__(
        self,
        *,
        cache: FeatureCache,
        refresh_interval: int = 300,
        timeout: float = 10.0,
        fetcher: JsonFetcher = fetch_json,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.cache = cache
        self.refresh_interval = refresh_interval
        self.timeout = timeout
        self.fetcher = fetcher
        self.clock = clock
        self._status = ProviderStatus(name=self.name)
        self._memory: FeatureCollection | None = None
        self._lock = Lock()
        self._generation = 0

    @property
    def status(self) -> ProviderStatus:
        cached = self._cached()
        self._status.cache_available = cached is not None
        self._status.cache_age_seconds = (
            max(0, round(self._age(cached), 3)) if cached is not None else None
        )
        if cached is not None:
            self._status.feature_count = len(cached.features)
            self._status.last_success_at = cached.source.retrieved_at
            # Staleness follows the cache's age, not only the last refresh outcome.
            self._status.cache_stale = self._age(cached) > self.refresh_interval
        else:
            self._status.cache_stale = False
        return self._status

    def _age(self, collection: FeatureCollection) -> float:
        return (self.clock() - parse_timestamp(collection.source.retrieved_at)).total_seconds()

    def _cached(self) -> FeatureCollection | None:
        return self._memory or self.cache.load("earthquakes")

    def get_features(self, layer_id: str) -> FeatureCollection:
        self._require_layer(layer_id)
        cached = self._cached()
        if cached is not None:
            age = self._age(cached)
            if age <= self.refresh_interval:
                self._memory = cached
                self._set_success(cached, serving_cache=True, stale=False)
                return cached.cached_copy(stale=False, age_seconds=age)
        return self.refresh(layer_id, force=False)

    def refresh(self, layer_id: str, *, force: bool = True) -> FeatureCollection:
        self._require_layer(layer_id)
        generation = self._generation
        cached = self._cached()
        if cached is not None and self._lock.locked():
            age = self._age(cached)
            return cached.cached_copy(stale=age > self.refresh_interval, age_seconds=age)
        with self._lock:
            cached = self._cached()
            if generation != self._generation or (not force and cached is not None and self._age(cached) <= self.refresh_interval):
                if cached is not None:
                    age = self._age(cached)
                    return cached.cached_copy(stale=age > self.refresh_interval, age_seconds=age)
                raise ProviderUnavailable("USGS refresh failed; no valid cache exists")
            attempted_at = isoformat(self.clock())
            self._status.state = "refreshing"
            self._status.last_attempt_at = attempted_at
            try:
                raw = self.fetcher(USGS_EARTHQUAKES_URL, self.timeout)
                collection = self._normalize(raw, retrieved_at=attempted_at)
                self._memory = collection
                self._set_success(collection, serving_cache=False, stale=False)
                try:
                    self.cache.save(collection)
                except OSError:
                    self._status.state = "degraded"
                    self._status.last_error = "Fresh data available; disk cache could not be saved"
                return collection
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                cached = self._cached()
                if cached is not None:
                    age = self._age(cached)
                    fallback = cached.cached_copy(stale=True, age_seconds=age)
                    self._status.state = "degraded"
                    self._status.last_error = error
                    self._status.serving_cache = True
                    self._status.cache_stale = True
                    self._status.cache_available = True
                    self._status.cache_age_seconds = max(0, round(age, 3))
                    self._status.feature_count = len(fallback.features)
                    return fallback
                self._status.state = "unavailable"
                self._status.last_error = error
                self._status.serving_cache = False
                self._status.cache_stale = False
                self._status.cache_available = False
                self._status.cache_age_seconds = None
                raise ProviderUnavailable(
                    "USGS earthquakes are unavailable and no valid cache exists"
                ) from exc
            finally:
                self._generation += 1

    def _set_success(
        self, collection: FeatureCollection, *, serving_cache: bool, stale: bool
    ) -> None:
        self._status.state = "ready"
        self._status.last_success_at = collection.source.retrieved_at
        self._status.last_error = None
        self._status.cache_available = True
        self._status.cache_age_seconds = max(0, round(self._age(collection), 3))
        self._status.serving_cache = serving_cache
        self._status.cache_stale = stale
        self._status.feature_count = len(collection.features)

    @staticmethod
    def _require_layer(layer_id: str) -> None:
        if layer_id != "earthquakes":
            raise KeyError(f"USGS provider does not support layer: {layer_id}")

    def _normalize(
        self, payload: dict[str, Any], *, retrieved_at: str
    ) -> FeatureCollection:
        if payload.get("type") != "FeatureCollection":
            raise ValueError("USGS response is not a FeatureCollection")
        metadata = payload.get("metadata") or {}
        generated = metadata.get("generated")
        upstream_generated_at = (
            timestamp_from_millis(generated) if generated is not None else None
        )
        features = tuple(
            self._normalize_feature(item, retrieved_at=retrieved_at)
            for item in payload.get("features", [])
        )
        return FeatureCollection(
            layer_id="earthquakes",
            features=features,
            generated_at=upstream_generated_at or retrieved_at,
            source=SourceMetadata(
                provider=self.name,
                source_url=USGS_EARTHQUAKES_URL,
                attribution=USGS_ATTRIBUTION,
                license_url=USGS_LICENSE_URL,
                retrieved_at=retrieved_at,
                upstream_generated_at=upstream_generated_at,
            ),
        )

    @staticmethod
    def _normalize_feature(
        feature: dict[str, Any], *, retrieved_at: str
    ) -> NormalizedFeature:
        source_id = feature.get("id")
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        if not source_id:
            raise ValueError("USGS feature is missing id")
        observed_at = timestamp_from_millis(properties.get("time"))
        updated_at = timestamp_from_millis(properties.get("updated"))
        source_url = properties.get("url")
        if not source_url:
            raise ValueError(f"USGS feature {source_id} is missing its source URL")
        return NormalizedFeature(
            id=f"usgs:{source_id}",
            geometry={
                "type": geometry.get("type"),
                "coordinates": geometry.get("coordinates"),
            },
            properties={
                "kind": "earthquake",
                "observed_at": observed_at,
                "updated_at": updated_at,
                "title": properties.get("title"),
                "place": properties.get("place"),
                "magnitude": properties.get("mag"),
                "magnitude_type": properties.get("magType"),
                "status": properties.get("status"),
                "significance": properties.get("sig"),
                "detail_url": properties.get("detail"),
            },
            provenance={
                "provider": "usgs",
                "source_id": source_id,
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "attribution": USGS_ATTRIBUTION,
                "license_url": USGS_LICENSE_URL,
            },
        )
