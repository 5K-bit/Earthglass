"""NOAA National Weather Service active-alerts provider (watches, warnings, advisories)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
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

LAYER_ID = "weather-alerts"
NWS_ALERTS_URL = "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update"
NWS_ATTRIBUTION = "NOAA National Weather Service"
NWS_LICENSE_URL = "https://www.weather.gov/disclaimer"
# NWS requires an identifying User-Agent on every request.
NWS_USER_AGENT = "EarthGlass/0.4 (+https://github.com/5K-bit/Earthglass)"

JsonFetcher = Callable[[str, float], dict[str, Any]]


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    response = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"Accept": "application/geo+json", "User-Agent": NWS_USER_AGENT},
    )
    response.raise_for_status()
    return response.json()


def _optional_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return isoformat(parse_timestamp(value))


class NWSAlertsProvider:
    """Normalizes NWS CAP alerts.

    Safety rules: only ``status == "Actual"`` alerts are kept (never Test/Exercise),
    and alerts past their expiry are removed on every read, including cache replays,
    so an expired warning can never be presented as active.
    """

    name = "nws"

    def __init__(
        self,
        *,
        cache: FeatureCache,
        refresh_interval: int = 120,
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
        self._points: dict[str, FeatureCollection] = {}

    # ---- status -----------------------------------------------------------------
    @property
    def status(self) -> ProviderStatus:
        cached = self._cached()
        self._status.cache_available = cached is not None
        if cached is not None:
            age = self._age(cached)
            self._status.cache_age_seconds = max(0, round(age, 3))
            self._status.feature_count = len(self._unexpired(cached).features)
            self._status.last_success_at = cached.source.retrieved_at
            self._status.cache_stale = age > self.refresh_interval
        else:
            self._status.cache_age_seconds = None
            self._status.cache_stale = False
        return self._status

    def _age(self, collection: FeatureCollection) -> float:
        return (self.clock() - parse_timestamp(collection.source.retrieved_at)).total_seconds()

    def _cached(self) -> FeatureCollection | None:
        return self._memory or self.cache.load(LAYER_ID)

    # ---- expiry -----------------------------------------------------------------
    def _unexpired(self, collection: FeatureCollection) -> FeatureCollection:
        now = self.clock()
        kept = []
        for feature in collection.features:
            end = feature.properties.get("ends") or feature.properties.get("expires")
            if end and parse_timestamp(end) <= now:
                continue
            kept.append(feature)
        if len(kept) == len(collection.features):
            return collection
        return replace(collection, features=tuple(kept))

    # ---- LayerProvider ----------------------------------------------------------
    def get_features(self, layer_id: str) -> FeatureCollection:
        self._require_layer(layer_id)
        cached = self._cached()
        if cached is not None and self._age(cached) <= self.refresh_interval:
            self._memory = cached
            age = self._age(cached)
            return self._unexpired(cached).cached_copy(stale=False, age_seconds=age)
        return self.refresh(layer_id, force=False)

    def refresh(self, layer_id: str, *, force: bool = True) -> FeatureCollection:
        self._require_layer(layer_id)
        with self._lock:
            cached = self._cached()
            if not force and cached is not None and self._age(cached) <= self.refresh_interval:
                return self._unexpired(cached).cached_copy(stale=False, age_seconds=self._age(cached))
            attempted_at = isoformat(self.clock())
            self._status.state = "refreshing"
            self._status.last_attempt_at = attempted_at
            try:
                raw = self.fetcher(NWS_ALERTS_URL, self.timeout)
                collection = self._normalize(raw, retrieved_at=attempted_at)
            except Exception as exc:  # noqa: BLE001 - any upstream failure falls back to cache
                return self._fallback(cached, f"{type(exc).__name__}: {exc}")
            self._memory = collection
            self._status.state = "ready"
            self._status.last_success_at = attempted_at
            self._status.last_error = None
            self._status.serving_cache = False
            self._status.feature_count = len(collection.features)
            try:
                self.cache.save(collection)
            except OSError:
                self._status.state = "degraded"
                self._status.last_error = "Fresh data available; disk cache could not be saved"
            return collection

    def _fallback(self, cached: FeatureCollection | None, error: str) -> FeatureCollection:
        self._status.last_error = error
        if cached is None:
            self._status.state = "unavailable"
            self._status.serving_cache = False
            raise ProviderUnavailable("NWS alerts are unavailable and no valid cache exists")
        age = self._age(cached)
        self._status.state = "degraded"
        self._status.serving_cache = True
        self._status.cache_stale = True
        return self._unexpired(cached).cached_copy(stale=True, age_seconds=age)

    def get_point_alerts(self, latitude: float, longitude: float) -> FeatureCollection:
        """Alerts affecting one location, resolved by NWS (covers zone-only alerts too).

        Held in memory only, rounded to ~1 km and bounded in size. On upstream failure the
        last result for that point is served marked stale; with none, ProviderUnavailable.
        """

        key = f"{latitude:.2f},{longitude:.2f}"
        url = f"{NWS_ALERTS_URL}&point={latitude:.2f},{longitude:.2f}"
        with self._lock:
            held = self._points.get(key)
            if held is not None and self._age(held) <= self.refresh_interval:
                return self._unexpired(held).cached_copy(stale=False, age_seconds=self._age(held))
            retrieved_at = isoformat(self.clock())
            try:
                collection = self._normalize(self.fetcher(url, self.timeout), retrieved_at=retrieved_at)
            except Exception as exc:  # noqa: BLE001
                if held is None:
                    raise ProviderUnavailable("NWS point alerts are unavailable") from exc
                return self._unexpired(held).cached_copy(stale=True, age_seconds=self._age(held))
            collection = replace(collection, source=replace(collection.source, source_url=url))
            if len(self._points) >= 64:
                self._points.pop(next(iter(self._points)))
            self._points[key] = collection
            return collection

    @staticmethod
    def _require_layer(layer_id: str) -> None:
        if layer_id != LAYER_ID:
            raise KeyError(f"NWS provider does not support layer: {layer_id}")

    # ---- normalization ----------------------------------------------------------
    def _normalize(self, payload: dict[str, Any], *, retrieved_at: str) -> FeatureCollection:
        if payload.get("type") != "FeatureCollection":
            raise ValueError("NWS response is not a FeatureCollection")
        features = tuple(
            normalized
            for item in payload.get("features", [])
            if (normalized := self._normalize_feature(item, retrieved_at=retrieved_at)) is not None
        )
        return self._unexpired(
            FeatureCollection(
                layer_id=LAYER_ID,
                features=features,
                generated_at=_optional_timestamp(payload.get("updated")) or retrieved_at,
                source=SourceMetadata(
                    provider=self.name,
                    source_url=NWS_ALERTS_URL,
                    attribution=NWS_ATTRIBUTION,
                    license_url=NWS_LICENSE_URL,
                    retrieved_at=retrieved_at,
                    upstream_generated_at=_optional_timestamp(payload.get("updated")),
                ),
            )
        )

    @staticmethod
    def _normalize_feature(feature: dict[str, Any], *, retrieved_at: str) -> NormalizedFeature | None:
        properties = feature.get("properties") or {}
        # Never present test or exercise products as real alerts.
        if properties.get("status") != "Actual":
            return None
        source_id = feature.get("id") or properties.get("id")
        if not source_id:
            raise ValueError("NWS alert is missing id")
        sent = _optional_timestamp(properties.get("sent"))
        if sent is None:
            raise ValueError(f"NWS alert {source_id} is missing its sent time")
        geometry = feature.get("geometry")
        source_url = source_id if str(source_id).startswith("https://") else NWS_ALERTS_URL
        return NormalizedFeature(
            id=f"nws:{source_id}",
            geometry=geometry if geometry else None,
            properties={
                "kind": "weather_alert",
                "observed_at": sent,
                "event": properties.get("event"),
                "headline": properties.get("headline"),
                "severity": properties.get("severity"),
                "urgency": properties.get("urgency"),
                "certainty": properties.get("certainty"),
                "area_desc": properties.get("areaDesc"),
                "message_type": properties.get("messageType"),
                "sender_name": properties.get("senderName"),
                "effective": _optional_timestamp(properties.get("effective")),
                "onset": _optional_timestamp(properties.get("onset")),
                "expires": _optional_timestamp(properties.get("expires")),
                "ends": _optional_timestamp(properties.get("ends")),
                "affected_zones": list(properties.get("affectedZones") or []),
                "located": bool(geometry),
            },
            provenance={
                "provider": "nws",
                "source_id": str(source_id),
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "attribution": NWS_ATTRIBUTION,
                "license_url": NWS_LICENSE_URL,
            },
        )
