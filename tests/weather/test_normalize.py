import numpy as np
import pytest

from earthglass.weather.gfs.normalize import EXPECTED_NX, EXPECTED_NY, kelvin_to_celsius, normalize_temperature_grid


def test_kelvin_to_celsius() -> None:
    assert kelvin_to_celsius(np.array([[273.15]], dtype=np.float32))[0, 0] == pytest.approx(0)


def test_normalize_rolls_longitude_and_keeps_north_to_south_order() -> None:
    latitudes = np.linspace(90, -90, EXPECTED_NY, dtype=np.float32)
    longitudes = np.arange(0, 360, 0.25, dtype=np.float32)
    kelvin = np.tile(longitudes, (EXPECTED_NY, 1)).astype(np.float32) + 273.15

    normalized = normalize_temperature_grid(kelvin, latitudes, longitudes)

    assert normalized.shape == (EXPECTED_NY, EXPECTED_NX)
    assert normalized[0, 0] == pytest.approx(180)
    assert normalized[0, -1] == pytest.approx(179.75)


def test_normalize_flips_ascending_latitudes() -> None:
    latitudes = np.linspace(-90, 90, EXPECTED_NY, dtype=np.float32)
    longitudes = np.arange(0, 360, 0.25, dtype=np.float32)
    kelvin = np.tile(np.arange(EXPECTED_NY, dtype=np.float32)[:, None], (1, EXPECTED_NX)) + 273.15

    normalized = normalize_temperature_grid(kelvin, latitudes, longitudes)

    assert normalized[0, 0] == pytest.approx(EXPECTED_NY - 1)
