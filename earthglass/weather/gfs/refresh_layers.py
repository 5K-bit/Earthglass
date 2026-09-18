from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from earthglass.weather.gfs.cycles import candidate_cycles, cycle_id
from earthglass.weather.gfs.decoder import GfsDecodeError, decode_layer_grib
from earthglass.weather.gfs.layers import GfsLayerSpec, LAYER_SPECS, get_layer_spec
from earthglass.weather.gfs.nomads import GfsCycleUnavailable, GfsNetworkError, resolve_and_download_layer
from earthglass.weather.gfs.normalize import (
    GfsNormalizeError,
    normalize_layer_fields,
    validate_layer_values,
    validate_normalized_grid,
)
from earthglass.weather.models.metadata import LayerAssets, LayerProvenance, LayerStats, WeatherLayerMetadata
from earthglass.weather.rendering.palettes import write_layer_png
from earthglass.weather.storage.cache import (
    ensure_runtime_dirs,
    publish_layer_latest,
    raw_root,
    staging_root,
    write_layer_status,
)


def _weather_url(filename: str) -> str:
    return f"/weather/gfs/latest/{filename}"


def _metadata_filename(spec: GfsLayerSpec) -> str:
    return "metadata.json" if spec.id == "temperature" else f"{spec.id}.json"


def _component_filename(spec: GfsLayerSpec, field_id: str) -> str:
    return f"{spec.id}.f32" if spec.kind == "scalar" and field_id == "values" else f"{spec.id}_{field_id}.f32"


def _image_filename(spec: GfsLayerSpec) -> str:
    return f"{spec.id}.png" if spec.render_field == "values" else f"{spec.id}_{spec.render_field}.png"


def _render_values(spec: GfsLayerSpec, fields: dict[str, np.ndarray]) -> np.ndarray:
    if spec.render_field == "speed":
        return np.hypot(fields["u"], fields["v"]).astype("<f4", copy=False)
    return fields[spec.render_field].astype("<f4", copy=False)


def _write_float32(values: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values.astype("<f4", copy=False).tofile(path)


def _assets(spec: GfsLayerSpec) -> tuple[LayerAssets, dict[str, str]]:
    image = _image_filename(spec)
    filenames: dict[str, str] = {"image": image}

    if spec.kind == "vector":
        filenames["u"] = _component_filename(spec, "u")
        filenames["v"] = _component_filename(spec, "v")
        return (
            LayerAssets(
                image=_weather_url(image),
                u=_weather_url(filenames["u"]),
                v=_weather_url(filenames["v"]),
            ),
            filenames,
        )

    values = _component_filename(spec, "values")
    filenames["values"] = values
    return (
        LayerAssets(image=_weather_url(image), values=_weather_url(values)),
        filenames,
    )


def _stats(values: np.ndarray) -> LayerStats:
    return LayerStats(
        min=float(np.min(values)),
        max=float(np.max(values)),
        mean=float(np.mean(values)),
    )


def _metadata(spec: GfsLayerSpec, cycle: datetime, render_values: np.ndarray) -> WeatherLayerMetadata:
    generated_at = datetime.now(timezone.utc)
    assets, _ = _assets(spec)
    return WeatherLayerMetadata(
        id=spec.id,
        variable=spec.variable_label,
        level=spec.level_label,
        units=spec.unit,
        cycle=cycle,
        forecastHour=0,
        generatedAt=generated_at,
        status="ready",
        kind=spec.kind,  # type: ignore[arg-type]
        assets=assets,
        stats=_stats(render_values),
        provenance=LayerProvenance(
            sourceSystem="NOAA_GFS",
            model="Global Forecast System 0.25 degree",
            provider="NOAA NOMADS",
            dataKind="model_analysis",
            cycle=cycle,
            forecastHour=0,
            generatedAt=generated_at,
            transformationNotes=[
                "Fetched via the NOAA NOMADS GFS GRIB filter as forecast hour f000.",
                *spec.transformation_notes,
            ],
        ),
    )


def _publish(
    spec: GfsLayerSpec,
    staged: Path,
    cycle: datetime,
    fields: dict[str, np.ndarray],
    render_values: np.ndarray,
) -> WeatherLayerMetadata:
    write_layer_png(render_values, staged / _image_filename(spec), spec.palette)

    _, filenames = _assets(spec)
    if spec.kind == "vector":
        for field_id in ("u", "v"):
            _write_float32(fields[field_id], staged / filenames[field_id])
    else:
        _write_float32(fields["values"], staged / filenames["values"])

    metadata = _metadata(spec, cycle, render_values)
    metadata_filename = _metadata_filename(spec)
    (staged / metadata_filename).write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

    publish_files = [name for key, name in filenames.items() if key != "image"]
    publish_files.insert(0, filenames["image"])

    if spec.id == "temperature":
        (staged / "temperature.json").write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
        publish_files.extend(["temperature.json", metadata_filename])
    else:
        publish_files.append(metadata_filename)

    publish_layer_latest(staged, tuple(publish_files))
    return metadata


def refresh_layer(layer_id: str, now: datetime | None = None) -> WeatherLayerMetadata:
    spec = get_layer_spec(layer_id)
    ensure_runtime_dirs()
    write_layer_status(spec.id, "refreshing", None)

    try:
        download = resolve_and_download_layer(spec, candidate_cycles(now, count=4), raw_root())
        run_id = f"{spec.id}_{cycle_id(download.cycle)}_f000"
        staged = staging_root(run_id)
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True, exist_ok=True)

        decoded_fields, latitudes, longitudes = decode_layer_grib(download.path, spec)
        fields = normalize_layer_fields(decoded_fields, latitudes, longitudes, spec)
        for field_id, values in fields.items():
            validate_normalized_grid(values, f"{spec.id}/{field_id}")

        render_values = _render_values(spec, fields)
        validate_layer_values(render_values, spec, f"{spec.id}/{spec.render_field}")
        metadata = _publish(spec, staged, download.cycle, fields, render_values)

        write_layer_status(spec.id, "ready", None)
        return metadata
    except GfsCycleUnavailable as exc:
        write_layer_status(spec.id, "stale", f"NOAA cycle unavailable: {exc}")
        raise
    except GfsNetworkError as exc:
        write_layer_status(spec.id, "stale", f"NOAA network failure: {exc}")
        raise
    except GfsDecodeError as exc:
        write_layer_status(spec.id, "error", f"GRIB decoder failure: {exc}")
        raise
    except GfsNormalizeError as exc:
        write_layer_status(spec.id, "error", f"GFS normalization failure: {exc}")
        raise


def refresh_all_layers(now: datetime | None = None) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for spec in LAYER_SPECS:
        try:
            metadata = refresh_layer(spec.id, now)
            results[spec.id] = {
                "status": "ready",
                "metadata": metadata.model_dump(mode="json"),
            }
        except Exception as exc:
            results[spec.id] = {
                "status": "error",
                "error": str(exc),
            }
    return results


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args:
        metadata = refresh_layer(args[0])
        print(metadata.model_dump_json(indent=2))
        return 0

    results = refresh_all_layers()
    print(json.dumps(results, indent=2, default=str))
    return 0 if any(result["status"] == "ready" for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
