"""Default EarthGlass runtime composition."""

from __future__ import annotations

import os
from pathlib import Path

from earthglass.cache import FeatureCache
from earthglass.layers import registry
from earthglass.nws import NWSAlertsProvider
from earthglass.providers import ProviderManager
from earthglass.usgs import USGSEarthquakeProvider


def build_provider_manager(cache_dir: Path | None = None) -> ProviderManager:
    configured_cache = cache_dir or Path(
        os.getenv("EARTHGLASS_CACHE_DIR", ".earthglass-cache")
    )
    manager = ProviderManager(registry)
    earthquakes = registry.get("earthquakes")
    manager.register(
        USGSEarthquakeProvider(
            cache=FeatureCache(configured_cache),
            refresh_interval=earthquakes.refresh_interval or 300,
        )
    )
    alerts = registry.get("weather-alerts")
    manager.register(
        NWSAlertsProvider(
            cache=FeatureCache(configured_cache),
            refresh_interval=alerts.refresh_interval or 120,
        )
    )
    return manager


provider_manager = build_provider_manager()
