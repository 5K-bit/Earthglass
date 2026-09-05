"""Renderer-agnostic geospatial layer definitions and registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

GeometryType = Literal["point", "line", "polygon", "raster", "volume"]
LayerStatus = Literal["ready", "unavailable", "error"]


@dataclass(frozen=True, slots=True)
class LayerDefinition:
    """Metadata describing a geospatial layer independent of any renderer."""

    id: str
    name: str
    description: str
    category: str
    geometry: GeometryType
    provider: str
    enabled: bool = True
    refresh_interval: int | None = None
    attribution: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class LayerRegistry:
    """In-memory registry consumed by APIs, CLIs, and external renderers."""

    def __init__(self) -> None:
        self._layers: dict[str, LayerDefinition] = {}

    def register(self, layer: LayerDefinition) -> None:
        if layer.id in self._layers:
            raise ValueError(f"layer already registered: {layer.id}")
        self._layers[layer.id] = layer

    def get(self, layer_id: str) -> LayerDefinition:
        try:
            return self._layers[layer_id]
        except KeyError as exc:
            raise KeyError(f"unknown layer: {layer_id}") from exc

    def list(self, *, enabled_only: bool = False) -> list[LayerDefinition]:
        layers = self._layers.values()
        if enabled_only:
            layers = (layer for layer in layers if layer.enabled)
        return sorted(layers, key=lambda layer: layer.id)


registry = LayerRegistry()
registry.register(
    LayerDefinition(
        id="earthquakes",
        name="Earthquakes",
        description="Recent global seismic events.",
        category="geology",
        geometry="point",
        provider="usgs",
        enabled=True,
        refresh_interval=300,
        attribution="U.S. Geological Survey (USGS)",
    )
)


def get_layers() -> list[dict[str, object]]:
    """Compatibility helper returning serializable layer metadata."""

    return [layer.as_dict() for layer in registry.list()]
