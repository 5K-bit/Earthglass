import numpy as np

from earthglass.weather.models.metadata import TemperatureGrid


def sample_grid(values: np.ndarray, grid: TemperatureGrid, lon: float, lat: float) -> float:
    wrapped_lon = ((lon - grid.lonMin) % 360) + grid.lonMin
    col = int((wrapped_lon - grid.lonMin) / grid.dx) % grid.nx
    row = int((grid.latMax - lat) / grid.dy)
    row = max(0, min(grid.ny - 1, row))
    return float(values[row, col])


def test_longitude_180_maps_to_minus_180_column() -> None:
    grid = TemperatureGrid()
    values = np.zeros((grid.ny, grid.nx), dtype=np.float32)
    values[:, 0] = 42

    assert sample_grid(values, grid, 180, 0) == 42
