from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from earthglass.weather.gfs.layers import GfsLayerSpec, get_layer_spec


class GfsDecodeError(RuntimeError):
    pass


def _find_data_variable(dataset: xr.Dataset, candidates: tuple[str, ...]) -> str:
    lowered = {name.lower(): name for name in dataset.data_vars}
    for candidate in candidates:
        match = lowered.get(candidate.lower())
        if match:
            return match

    if len(dataset.data_vars) == 1:
        return next(iter(dataset.data_vars))

    available = ", ".join(dataset.data_vars)
    raise KeyError(f"none of {candidates} found; available variables: {available}")


def decode_layer_grib(path: Path, spec: GfsLayerSpec) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    try:
        dataset = xr.open_dataset(path, engine="cfgrib")
    except Exception as exc:  # pragma: no cover - depends on local eccodes installation
        raise GfsDecodeError(f"Could not decode GRIB2 file: {exc}") from exc

    try:
        fields: dict[str, np.ndarray] = {}
        for field in spec.fields:
            variable_name = _find_data_variable(dataset, field.name_candidates)
            fields[field.id] = dataset[variable_name].values.astype(np.float32)

        latitudes = dataset["latitude"].values.astype(np.float32)
        longitudes = dataset["longitude"].values.astype(np.float32)
    except Exception as exc:
        raise GfsDecodeError(f"Decoded GRIB2 did not contain usable {spec.id} fields: {exc}") from exc
    finally:
        dataset.close()

    return fields, latitudes, longitudes


def decode_temperature_grib(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fields, latitudes, longitudes = decode_layer_grib(path, get_layer_spec("temperature"))
    return fields["values"], latitudes, longitudes
