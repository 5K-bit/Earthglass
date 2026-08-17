"""Provider interfaces for renderer-independent geospatial data sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class FeatureCollection:
    """Portable GeoJSON-like payload returned by EarthGlass providers."""

    layer_id: str
    features: list[dict[str, Any]]
    generated_at: str | None = None
    source: str | None = None

    def as_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": self.features,
            "metadata": {
                "layer_id": self.layer_id,
                "generated_at": self.generated_at,
                "source": self.source,
            },
        }


class LayerProvider(Protocol):
    """Contract for live, cached, or local geospatial layer providers."""

    name: str

    def refresh(self) -> None:
        """Refresh provider state without changing renderer concerns."""
        ...

    def get_features(self, layer_id: str) -> FeatureCollection:
        """Return normalized geospatial features for a registered layer."""
        ...
