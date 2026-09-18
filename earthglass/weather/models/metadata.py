from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LayerStatus = Literal["ready", "refreshing", "stale", "missing", "error"]
LayerKind = Literal["scalar", "vector"]


class GlobalGrid(BaseModel):
    nx: Literal[1440] = 1440
    ny: Literal[721] = 721
    lonMin: Literal[-180] = -180
    lonMax: Literal[179.75] = 179.75
    latMin: Literal[-90] = -90
    latMax: Literal[90] = 90
    dx: Literal[0.25] = 0.25
    dy: Literal[0.25] = 0.25
    wrapLongitude: Literal[True] = True
    order: Literal["north-to-south, west-to-east"] = "north-to-south, west-to-east"


TemperatureGrid = GlobalGrid


class LayerAssets(BaseModel):
    image: str
    values: str | None = None
    u: str | None = None
    v: str | None = None


class LayerStats(BaseModel):
    min: float
    max: float
    mean: float


class LayerProvenance(BaseModel):
    sourceSystem: str
    model: str
    provider: str
    dataKind: Literal["model_analysis", "model_forecast", "observation", "reanalysis"]
    cycle: datetime
    forecastHour: int
    generatedAt: datetime
    transformationNotes: list[str] = Field(default_factory=list)


class WeatherLayerDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: str
    kind: LayerKind
    unit: str
    modelId: str
    enabled: bool = True
    defaultOpacity: float = 0.78
    canSample: bool = True
    canRender: bool = True
    overlayRole: Literal["primary", "optional"] = "primary"


class WeatherLayerMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: Literal["NOAA_GFS_0p25"] = "NOAA_GFS_0p25"
    variable: str
    level: str
    units: str
    cycle: datetime
    forecastHour: Literal[0] = 0
    generatedAt: datetime
    status: LayerStatus = "ready"
    kind: LayerKind
    grid: GlobalGrid = Field(default_factory=GlobalGrid)
    assets: LayerAssets
    stats: LayerStats
    provenance: LayerProvenance


TemperatureLayerMetadata = WeatherLayerMetadata


class RuntimeStatus(BaseModel):
    status: LayerStatus
    message: str | None = None
    updatedAt: datetime


class ModelDefinition(BaseModel):
    id: str
    name: str
    role: str
    status: Literal["active", "planned"]
    description: str
    requirements: list[str] = Field(default_factory=list)
