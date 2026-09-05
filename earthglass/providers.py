"""Provider contracts, normalized payloads, and lifecycle coordination."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from earthglass.layers import LayerRegistry

ProviderState = Literal[
    "idle", "refreshing", "ready", "degraded", "unavailable", "error"
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Provenance for a collection fetched from an external source."""

    provider: str
    source_url: str
    attribution: str
    retrieved_at: str
    license_url: str | None = None
    upstream_generated_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("provider", "source_url", "attribution"):
            if not getattr(self, name):
                raise ValueError(f"source {name} must not be empty")
        parse_timestamp(self.retrieved_at)
        if self.upstream_generated_at is not None:
            parse_timestamp(self.upstream_generated_at)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NormalizedFeature:
    """Validated, renderer-independent GeoJSON feature."""

    id: str
    geometry: dict[str, Any]
    properties: dict[str, Any]
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("feature id must not be empty")
        if self.geometry.get("type") != "Point":
            raise ValueError("the current normalized schema supports Point geometry")
        coordinates = self.geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) not in (2, 3):
            raise ValueError("point coordinates must contain longitude, latitude[, altitude]")
        if not all(isinstance(value, (int, float)) for value in coordinates):
            raise ValueError("point coordinates must be numeric")
        longitude, latitude = coordinates[:2]
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("point coordinates are outside geographic bounds")
        if not isinstance(self.properties, dict):
            raise ValueError("feature properties must be an object")
        parse_timestamp(self.properties.get("observed_at"))
        for key in ("provider", "source_id", "source_url", "retrieved_at"):
            if not self.provenance.get(key):
                raise ValueError(f"feature provenance requires {key}")
        parse_timestamp(self.provenance["retrieved_at"])

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": self.geometry,
            "properties": self.properties,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NormalizedFeature":
        if value.get("type") != "Feature":
            raise ValueError("normalized feature type must be Feature")
        return cls(
            id=value.get("id", ""),
            geometry=value.get("geometry", {}),
            properties=value.get("properties", {}),
            provenance=value.get("provenance", {}),
        )


@dataclass(frozen=True, slots=True)
class FeatureCollection:
    """Validated GeoJSON payload returned by EarthGlass providers."""

    layer_id: str
    features: tuple[NormalizedFeature, ...]
    generated_at: str
    source: SourceMetadata
    cache: dict[str, Any] = field(default_factory=lambda: {"status": "live", "stale": False})

    def __post_init__(self) -> None:
        if not self.layer_id:
            raise ValueError("collection layer_id must not be empty")
        parse_timestamp(self.generated_at)
        if self.cache.get("status") not in {"live", "cache"}:
            raise ValueError("cache status must be live or cache")
        if not isinstance(self.cache.get("stale"), bool):
            raise ValueError("cache stale flag must be boolean")

    def as_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [feature.as_dict() for feature in self.features],
            "metadata": {
                "layer_id": self.layer_id,
                "generated_at": self.generated_at,
                "source": self.source.as_dict(),
                "cache": self.cache,
            },
        }

    @classmethod
    def from_geojson(cls, value: dict[str, Any]) -> "FeatureCollection":
        if value.get("type") != "FeatureCollection":
            raise ValueError("payload type must be FeatureCollection")
        metadata = value.get("metadata") or {}
        return cls(
            layer_id=metadata.get("layer_id", ""),
            features=tuple(
                NormalizedFeature.from_dict(feature)
                for feature in value.get("features", [])
            ),
            generated_at=metadata.get("generated_at", ""),
            source=SourceMetadata(**(metadata.get("source") or {})),
            cache=metadata.get("cache") or {"status": "cache", "stale": True},
        )

    def cached_copy(self, *, stale: bool, age_seconds: float) -> "FeatureCollection":
        return FeatureCollection(
            layer_id=self.layer_id,
            features=self.features,
            generated_at=self.generated_at,
            source=self.source,
            cache={
                "status": "cache",
                "stale": stale,
                "age_seconds": max(0, round(age_seconds, 3)),
            },
        )


@dataclass(slots=True)
class ProviderStatus:
    name: str
    state: ProviderState = "idle"
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    cache_available: bool = False
    cache_age_seconds: float | None = None
    serving_cache: bool = False
    cache_stale: bool = False
    feature_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderUnavailable(RuntimeError):
    """Raised when neither a live response nor a valid cache is available."""


class LayerProvider(Protocol):
    name: str

    @property
    def status(self) -> ProviderStatus: ...

    def refresh(self, layer_id: str) -> FeatureCollection: ...

    def get_features(self, layer_id: str) -> FeatureCollection: ...


class ProviderManager:
    """Routes registered layers to providers without renderer knowledge."""

    def __init__(self, layers: LayerRegistry) -> None:
        self._layers = layers
        self._providers: dict[str, LayerProvider] = {}

    def register(self, provider: LayerProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"provider already registered: {provider.name}")
        self._providers[provider.name] = provider

    def provider_for(self, layer_id: str) -> LayerProvider:
        layer = self._layers.get(layer_id)
        try:
            return self._providers[layer.provider]
        except KeyError as exc:
            raise ProviderUnavailable(
                f"provider is not configured for layer {layer_id}: {layer.provider}"
            ) from exc

    def get_features(self, layer_id: str) -> FeatureCollection:
        return self.provider_for(layer_id).get_features(layer_id)

    def refresh(self, layer_id: str) -> FeatureCollection:
        return self.provider_for(layer_id).refresh(layer_id)

    def statuses(self) -> list[dict[str, Any]]:
        return [
            provider.status.as_dict()
            for provider in sorted(self._providers.values(), key=lambda item: item.name)
        ]
