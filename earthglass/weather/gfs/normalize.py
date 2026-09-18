from __future__ import annotations

import numpy as np

from earthglass.weather.gfs.layers import GfsLayerSpec, get_layer_spec, kelvin_to_celsius as _kelvin_to_celsius

EXPECTED_NX = 1440
EXPECTED_NY = 721
DX = 0.25
DY = 0.25


class GfsNormalizeError(ValueError):
    pass


def kelvin_to_celsius(values: np.ndarray) -> np.ndarray:
    return _kelvin_to_celsius(values)


def normalize_global_grid(
    values: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    label: str = "GFS field",
) -> np.ndarray:
    if values.shape != (EXPECTED_NY, EXPECTED_NX):
        raise GfsNormalizeError(
            f"Expected {label} grid {(EXPECTED_NY, EXPECTED_NX)}, got {values.shape}"
        )

    if latitudes.shape[0] != EXPECTED_NY or longitudes.shape[0] != EXPECTED_NX:
        raise GfsNormalizeError("Latitude/longitude coordinate lengths do not match GFS 0.25 grid")

    normalized = values.astype(np.float32)

    if latitudes[0] < latitudes[-1]:
        normalized = np.flipud(normalized)
        latitudes = latitudes[::-1]

    if not np.isclose(latitudes[0], 90, atol=0.001) or not np.isclose(latitudes[-1], -90, atol=0.001):
        raise GfsNormalizeError("Latitude coordinates must cover 90 to -90 degrees")

    rolled_longitudes = ((longitudes + 180) % 360) - 180
    order = np.argsort(rolled_longitudes)
    sorted_longitudes = rolled_longitudes[order]
    normalized = normalized[:, order].astype("<f4", copy=False)

    if not np.isclose(sorted_longitudes[0], -180, atol=0.001):
        raise GfsNormalizeError("Longitude grid does not start at -180 after rolling")
    if not np.isclose(sorted_longitudes[-1], 179.75, atol=0.001):
        raise GfsNormalizeError("Longitude grid does not end at 179.75 after rolling")

    return normalized


def normalize_temperature_grid(
    kelvin: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
) -> np.ndarray:
    normalized_kelvin = normalize_global_grid(kelvin, latitudes, longitudes, "temperature")
    return kelvin_to_celsius(normalized_kelvin)


def normalize_layer_fields(
    fields: dict[str, np.ndarray],
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    spec: GfsLayerSpec,
) -> dict[str, np.ndarray]:
    normalized: dict[str, np.ndarray] = {}
    for field in spec.fields:
        if field.id not in fields:
            raise GfsNormalizeError(f"Decoded {spec.id} data is missing field {field.id}")
        raw = normalize_global_grid(fields[field.id], latitudes, longitudes, f"{spec.id}/{field.id}")
        normalized[field.id] = field.transform(raw).astype("<f4", copy=False)
    return normalized


def validate_layer_values(values: np.ndarray, spec: GfsLayerSpec, label: str | None = None) -> None:
    name = label or spec.id
    validate_normalized_grid(values, name)

    minimum = float(np.nanmin(values))
    maximum = float(np.nanmax(values))
    if minimum < spec.value_range.minimum or maximum > spec.value_range.maximum:
        raise GfsNormalizeError(
            f"{name} grid has implausible values: {minimum:.2f} to {maximum:.2f} {spec.unit}"
        )


def validate_normalized_grid(values: np.ndarray, label: str) -> None:
    if values.shape != (EXPECTED_NY, EXPECTED_NX):
        raise GfsNormalizeError(f"Expected normalized {label} grid {(EXPECTED_NY, EXPECTED_NX)}, got {values.shape}")
    if not np.isfinite(values).all():
        raise GfsNormalizeError(f"{label} grid contains non-finite values")


def validate_temperature_values(celsius: np.ndarray) -> None:
    validate_layer_values(celsius, get_layer_spec("temperature"), "temperature")
