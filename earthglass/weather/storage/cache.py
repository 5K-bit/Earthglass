from __future__ import annotations

import json
import os
from contextvars import ContextVar

active_weather_root: ContextVar = ContextVar("active_weather_root", default=None)
weather_cancelled: ContextVar = ContextVar("weather_cancelled", default=lambda: False)
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from earthglass.weather.models.metadata import (
    LayerAssets,
    LayerProvenance,
    LayerStats,
    RuntimeStatus,
    TemperatureLayerMetadata,
    WeatherLayerMetadata,
)


def repository_root() -> Path:
    configured = os.environ.get("OBEOS_EARTH_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[3]


def weather_root() -> Path:
    active = active_weather_root.get()
    if active is not None:
        return active
    configured = os.environ.get("OBEOS_WEATHER_DATA_DIR")
    if configured:
        return Path(configured).resolve()
    return repository_root() / "data" / "weather" / "gfs"


def raw_root() -> Path:
    return weather_root() / "raw"


def latest_root() -> Path:
    return weather_root() / "latest"


def staging_root(run_id: str) -> Path:
    return weather_root() / "staging" / run_id


def status_path() -> Path:
    return weather_root() / "status.json"


def layer_status_path(layer_id: str) -> Path:
    return weather_root() / "status" / f"{layer_id}.json"


def layer_metadata_path(layer_id: str) -> Path:
    if layer_id == "temperature":
        legacy = latest_root() / "metadata.json"
        if legacy.exists():
            return legacy
    return latest_root() / f"{layer_id}.json"


def ensure_runtime_dirs() -> None:
    raw_root().mkdir(parents=True, exist_ok=True)
    latest_root().mkdir(parents=True, exist_ok=True)
    status_path().parent.mkdir(parents=True, exist_ok=True)
    (weather_root() / "status").mkdir(parents=True, exist_ok=True)


def read_latest_metadata() -> TemperatureLayerMetadata | None:
    metadata = read_layer_metadata("temperature")
    return metadata  # type: ignore[return-value]


def read_layer_metadata(layer_id: str) -> WeatherLayerMetadata | None:
    path = layer_metadata_path(layer_id)
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as handle:
        raw = handle.read()

    try:
        return WeatherLayerMetadata.model_validate_json(raw)
    except ValidationError:
        if layer_id != "temperature":
            raise
        return _read_legacy_temperature_metadata(raw)


def _read_legacy_temperature_metadata(raw: str) -> WeatherLayerMetadata:
    data = json.loads(raw)
    cycle = datetime.fromisoformat(data["cycle"].replace("Z", "+00:00"))
    generated_at = datetime.fromisoformat(data["generatedAt"].replace("Z", "+00:00"))
    stats = data.get("stats", {})
    assets = data.get("assets", {})

    return WeatherLayerMetadata(
        id="temperature",
        source=data.get("source", "NOAA_GFS_0p25"),
        variable=data.get("variable", "TMP"),
        level=data.get("level", "2 m above ground"),
        units=data.get("units", "C"),
        cycle=cycle,
        forecastHour=data.get("forecastHour", 0),
        generatedAt=generated_at,
        status=data.get("status", "ready"),
        kind="scalar",
        assets=LayerAssets(
            image=assets.get("image", "/weather/gfs/latest/temperature.png"),
            values=assets.get("values", "/weather/gfs/latest/temperature.f32"),
        ),
        stats=LayerStats(
            min=float(stats.get("min", stats.get("minC", 0))),
            max=float(stats.get("max", stats.get("maxC", 0))),
            mean=float(stats.get("mean", stats.get("meanC", 0))),
        ),
        provenance=LayerProvenance(
            sourceSystem="NOAA_GFS",
            model="Global Forecast System 0.25 degree",
            provider="NOAA NOMADS",
            dataKind="model_analysis",
            cycle=cycle,
            forecastHour=data.get("forecastHour", 0),
            generatedAt=generated_at,
            transformationNotes=["Loaded from the V1 temperature metadata cache."],
        ),
    )


def _status_model(status: RuntimeStatus | str, message: str | None = None) -> RuntimeStatus:
    return (
        status
        if isinstance(status, RuntimeStatus)
        else RuntimeStatus(
            status=status,
            message=message,
            updatedAt=datetime.now(timezone.utc),
        )
    )


def _write_status_file(path: Path, status_model: RuntimeStatus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(status_model.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def write_status(status: RuntimeStatus | str, message: str | None = None) -> None:
    ensure_runtime_dirs()
    _write_status_file(status_path(), _status_model(status, message))


def write_layer_status(layer_id: str, status: RuntimeStatus | str, message: str | None = None) -> None:
    ensure_runtime_dirs()
    model = _status_model(status, message)
    _write_status_file(layer_status_path(layer_id), model)
    if layer_id == "temperature":
        _write_status_file(status_path(), model)


def read_status() -> RuntimeStatus | None:
    path = status_path()
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as handle:
        return RuntimeStatus.model_validate_json(handle.read())


def read_layer_status(layer_id: str) -> RuntimeStatus | None:
    path = layer_status_path(layer_id)
    if not path.exists():
        if layer_id == "temperature":
            return read_status()
        return None

    with path.open("r", encoding="utf-8") as handle:
        return RuntimeStatus.model_validate_json(handle.read())


def publish_layer_latest(staged_dir: Path, filenames: tuple[str, ...]) -> None:
    ensure_runtime_dirs()
    target = latest_root()
    target.mkdir(parents=True, exist_ok=True)

    for filename in filenames:
        source = staged_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)

    # Replace metadata last so readers never see a new descriptor before assets exist.
    for filename in filenames:
        os.replace(staged_dir / filename, target / filename)

    shutil.rmtree(staged_dir, ignore_errors=True)


def publish_latest(staged_dir: Path) -> None:
    publish_layer_latest(staged_dir, ("temperature.png", "temperature.f32", "metadata.json"))
