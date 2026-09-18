from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from earthglass.weather.models.metadata import WeatherLayerDefinition

Transform = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class GfsFieldSpec:
    id: str
    variable: str
    level: str
    name_candidates: tuple[str, ...]
    transform: Transform
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValueRange:
    minimum: float
    maximum: float


@dataclass(frozen=True)
class GfsLayerSpec:
    id: str
    name: str
    description: str
    category: str
    kind: str
    unit: str
    fields: tuple[GfsFieldSpec, ...]
    render_field: str
    palette: str
    value_range: ValueRange
    default_opacity: float = 0.78
    overlay_role: str = "primary"

    @property
    def variable_label(self) -> str:
        return " + ".join(field.variable for field in self.fields)

    @property
    def level_label(self) -> str:
        levels = []
        for field in self.fields:
            if field.level not in levels:
                levels.append(field.level)
        return " + ".join(levels)

    @property
    def transformation_notes(self) -> list[str]:
        notes: list[str] = []
        for field in self.fields:
            notes.extend(field.notes)
        if self.id == "wind10m":
            notes.append("Wind speed render field derived from sqrt(u^2 + v^2).")
        return notes

    def as_definition(self) -> WeatherLayerDefinition:
        return WeatherLayerDefinition(
            id=self.id,
            name=self.name,
            description=self.description,
            category=self.category,
            kind=self.kind,  # type: ignore[arg-type]
            unit=self.unit,
            modelId="NOAA_GFS",
            defaultOpacity=self.default_opacity,
            overlayRole=self.overlay_role,  # type: ignore[arg-type]
        )


def identity(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32)


def kelvin_to_celsius(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32) - np.float32(273.15)


def precip_rate_to_mm_per_hour(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32) * np.float32(3600.0)


def pascal_to_hpa(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32) / np.float32(100.0)


def percentage(values: np.ndarray) -> np.ndarray:
    return np.clip(values.astype(np.float32), 0, 100)


LAYER_SPECS: tuple[GfsLayerSpec, ...] = (
    GfsLayerSpec(
        id="temperature",
        name="Temperature",
        description="Global 2 m air temperature from the latest GFS analysis.",
        category="weather",
        kind="scalar",
        unit="C",
        fields=(
            GfsFieldSpec(
                id="values",
                variable="TMP",
                level="2 m above ground",
                name_candidates=("t2m", "2t", "tmp"),
                transform=kelvin_to_celsius,
                notes=("Converted from Kelvin to Celsius.",),
            ),
        ),
        render_field="values",
        palette="temperature",
        value_range=ValueRange(-120, 80),
    ),
    GfsLayerSpec(
        id="wind10m",
        name="10 m Wind",
        description="Global 10 m wind vector field from the latest GFS analysis.",
        category="weather",
        kind="vector",
        unit="m/s",
        fields=(
            GfsFieldSpec(
                id="u",
                variable="UGRD",
                level="10 m above ground",
                name_candidates=("u10", "10u", "u", "ugrd"),
                transform=identity,
                notes=("U component is eastward wind in m/s.",),
            ),
            GfsFieldSpec(
                id="v",
                variable="VGRD",
                level="10 m above ground",
                name_candidates=("v10", "10v", "v", "vgrd"),
                transform=identity,
                notes=("V component is northward wind in m/s.",),
            ),
        ),
        render_field="speed",
        palette="wind",
        value_range=ValueRange(0, 150),
        default_opacity=0.72,
    ),
    GfsLayerSpec(
        id="precipRate",
        name="Precipitation Rate",
        description="Global surface precipitation rate from the latest GFS analysis.",
        category="weather",
        kind="scalar",
        unit="mm/hr",
        fields=(
            GfsFieldSpec(
                id="values",
                variable="PRATE",
                level="surface",
                name_candidates=("prate",),
                transform=precip_rate_to_mm_per_hour,
                notes=("Converted from kg m^-2 s^-1 water equivalent to mm/hr.",),
            ),
        ),
        render_field="values",
        palette="precipitation",
        value_range=ValueRange(0, 500),
        default_opacity=0.82,
    ),
    GfsLayerSpec(
        id="cloudCover",
        name="Cloud Cover",
        description="Global total cloud cover from the latest GFS analysis.",
        category="weather",
        kind="scalar",
        unit="%",
        fields=(
            GfsFieldSpec(
                id="values",
                variable="TCDC",
                level="entire atmosphere",
                name_candidates=("tcc", "tcdc"),
                transform=percentage,
                notes=("Clamped to 0-100 percent.",),
            ),
        ),
        render_field="values",
        palette="cloud",
        value_range=ValueRange(0, 100),
        default_opacity=0.42,
        overlay_role="optional",
    ),
    GfsLayerSpec(
        id="pressure",
        name="Mean Sea-Level Pressure",
        description="Global mean sea-level pressure from the latest GFS analysis.",
        category="weather",
        kind="scalar",
        unit="hPa",
        fields=(
            GfsFieldSpec(
                id="values",
                variable="PRMSL",
                level="mean sea level",
                name_candidates=("prmsl", "msl"),
                transform=pascal_to_hpa,
                notes=("Converted from Pascals to hPa.",),
            ),
        ),
        render_field="values",
        palette="pressure",
        value_range=ValueRange(800, 1100),
        default_opacity=0.68,
    ),
    GfsLayerSpec(
        id="humidity",
        name="Relative Humidity",
        description="Global 2 m relative humidity from the latest GFS analysis.",
        category="weather",
        kind="scalar",
        unit="%",
        fields=(
            GfsFieldSpec(
                id="values",
                variable="RH",
                level="2 m above ground",
                name_candidates=("r2", "2r", "rh"),
                transform=percentage,
                notes=("Clamped to 0-100 percent.",),
            ),
        ),
        render_field="values",
        palette="humidity",
        value_range=ValueRange(0, 100),
        default_opacity=0.7,
    ),
)

SPECS_BY_ID = {spec.id: spec for spec in LAYER_SPECS}


def get_layer_spec(layer_id: str) -> GfsLayerSpec:
    try:
        return SPECS_BY_ID[layer_id]
    except KeyError as exc:
        raise KeyError(f"unknown GFS layer: {layer_id}") from exc


def get_layer_definitions() -> list[dict[str, object]]:
    return [spec.as_definition().model_dump(mode="json") for spec in LAYER_SPECS]
