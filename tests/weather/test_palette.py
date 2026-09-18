import numpy as np

from earthglass.weather.rendering.palettes import values_to_rgba
from earthglass.weather.rendering.temperature_palette import temperature_to_rgba


def test_temperature_palette_outputs_rgba_bytes() -> None:
    values = np.array([[-50, 0, 50]], dtype=np.float32)

    rgba = temperature_to_rgba(values)

    assert rgba.shape == (1, 3, 4)
    assert rgba.dtype == np.uint8
    assert (rgba[..., 3] == 170).all()


def test_each_layer_palette_outputs_rgba_bytes() -> None:
    values = np.array([[0, 50, 100]], dtype=np.float32)

    for palette in ("wind", "precipitation", "cloud", "pressure", "humidity"):
        rgba = values_to_rgba(values, palette)
        assert rgba.shape == (1, 3, 4)
        assert rgba.dtype == np.uint8
