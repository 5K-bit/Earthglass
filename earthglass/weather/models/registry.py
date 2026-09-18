from __future__ import annotations

from earthglass.weather.models.metadata import ModelDefinition

MODEL_REGISTRY: tuple[ModelDefinition, ...] = (
    ModelDefinition(
        id="NOAA_GFS",
        name="NOAA Global Forecast System",
        role="operational live analysis and forecast source",
        status="active",
        description="Global 0.25 degree atmospheric model fields retrieved through NOMADS GRIB Filter.",
        requirements=["Internet access to NOAA NOMADS", "GRIB2 decoder"],
    ),
    ModelDefinition(
        id="OpenIFS",
        name="ECMWF OpenIFS",
        role="future physics-based model core candidate",
        status="planned",
        description="Open physics model candidate for future controlled forecast or historical replay runs.",
        requirements=["Linux/HPC-oriented runtime", "initial-condition datasets", "model configuration"],
    ),
    ModelDefinition(
        id="Earth2Studio",
        name="NVIDIA Earth-2 / Earth2Studio",
        role="future AI forecast, downscaling, nowcasting, and ensemble adapter",
        status="planned",
        description="AI weather workflow surface for future GPU-backed inference and post-processing.",
        requirements=["NVIDIA GPU for many model paths", "large model artifacts", "optional NGC/Docker access"],
    ),
    ModelDefinition(
        id="DestinE_DTE",
        name="Destination Earth Digital Twin Engine",
        role="future orchestration and data-fusion inspiration",
        status="planned",
        description="Reference architecture for extreme-scale simulation orchestration, interoperability, and data fusion.",
        requirements=["external platform integration", "HPC/cloud orchestration"],
    ),
)


def get_models() -> list[dict[str, object]]:
    return [model.model_dump(mode="json") for model in MODEL_REGISTRY]
