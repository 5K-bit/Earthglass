from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ColorStop = tuple[float, tuple[int, int, int, int]]

COLOR_RAMPS: dict[str, tuple[ColorStop, ...]] = {
    "temperature": (
        (-50.0, (24, 64, 176, 170)),
        (-25.0, (39, 145, 214, 170)),
        (0.0, (83, 190, 171, 170)),
        (15.0, (211, 220, 104, 170)),
        (30.0, (242, 155, 57, 170)),
        (42.0, (198, 57, 43, 170)),
        (50.0, (111, 28, 91, 170)),
    ),
    "wind": (
        (0.0, (32, 57, 126, 128)),
        (8.0, (33, 150, 210, 150)),
        (18.0, (91, 205, 142, 168)),
        (30.0, (240, 213, 80, 184)),
        (45.0, (232, 105, 58, 196)),
        (70.0, (176, 43, 132, 210)),
    ),
    "precipitation": (
        (0.0, (16, 42, 55, 0)),
        (0.2, (78, 176, 122, 88)),
        (2.0, (50, 170, 210, 156)),
        (8.0, (48, 83, 190, 190)),
        (20.0, (230, 210, 76, 210)),
        (50.0, (220, 74, 64, 224)),
    ),
    "cloud": (
        (0.0, (232, 238, 242, 0)),
        (25.0, (217, 227, 232, 80)),
        (55.0, (198, 207, 212, 132)),
        (80.0, (238, 238, 228, 170)),
        (100.0, (255, 255, 245, 206)),
    ),
    "pressure": (
        (940.0, (45, 82, 166, 158)),
        (980.0, (79, 160, 198, 158)),
        (1013.25, (236, 233, 206, 142)),
        (1030.0, (215, 145, 79, 158)),
        (1060.0, (175, 57, 88, 172)),
    ),
    "humidity": (
        (0.0, (178, 128, 72, 118)),
        (25.0, (223, 203, 108, 138)),
        (50.0, (109, 183, 111, 160)),
        (75.0, (64, 154, 194, 176)),
        (100.0, (53, 78, 165, 188)),
    ),
}


def values_to_rgba(values: np.ndarray, palette: str) -> np.ndarray:
    try:
        stops = COLOR_RAMPS[palette]
    except KeyError as exc:
        raise ValueError(f"unknown palette: {palette}") from exc

    positions = np.array([stop[0] for stop in stops], dtype=np.float32)
    colors = np.array([stop[1] for stop in stops], dtype=np.float32)
    clipped = np.clip(values.astype(np.float32), positions[0], positions[-1])

    lower = np.searchsorted(positions, clipped, side="right") - 1
    lower = np.clip(lower, 0, len(positions) - 2)
    upper = lower + 1

    span = positions[upper] - positions[lower]
    mix = np.divide(
        clipped - positions[lower],
        span,
        out=np.zeros_like(clipped, dtype=np.float32),
        where=span != 0,
    )[..., None]

    rgba = colors[lower] * (1 - mix) + colors[upper] * mix
    return np.clip(rgba, 0, 255).astype(np.uint8)


def write_layer_png(values: np.ndarray, path: Path, palette: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(values_to_rgba(values, palette), mode="RGBA")
    image.save(path)
