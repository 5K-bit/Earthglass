from __future__ import annotations

from pathlib import Path

import numpy as np

from earthglass.weather.rendering.palettes import values_to_rgba, write_layer_png


def temperature_to_rgba(celsius: np.ndarray) -> np.ndarray:
    return values_to_rgba(celsius, "temperature")


def write_temperature_png(celsius: np.ndarray, path: Path) -> None:
    write_layer_png(celsius, path, "temperature")
