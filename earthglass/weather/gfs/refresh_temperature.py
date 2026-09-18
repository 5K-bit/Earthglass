from __future__ import annotations

from datetime import datetime

from earthglass.weather.gfs.refresh_layers import refresh_layer
from earthglass.weather.models.metadata import TemperatureLayerMetadata


def refresh_temperature_layer(now: datetime | None = None) -> TemperatureLayerMetadata:
    return refresh_layer("temperature", now)


if __name__ == "__main__":
    layer = refresh_temperature_layer()
    print(layer.model_dump_json(indent=2))
