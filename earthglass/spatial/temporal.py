"""Project cached products at a requested UTC time without changing their evidence type."""

from datetime import datetime, timedelta

WEATHER = {"weather", "temperature", "wind", "pressure", "precipitation", "clouds"}


def project_weather(observation, at):
    if observation["layer"] not in WEATHER:
        return observation
    props = observation.get("properties", {})
    samples = props.get("forecast")
    if not samples:
        return observation
    candidates = [
        sample
        for sample in samples
        if datetime.fromisoformat(sample["valid_at"])
        <= at
        < datetime.fromisoformat(sample["valid_at"]) + timedelta(hours=1)
    ]
    if not candidates:
        return None
    sample = max(candidates, key=lambda value: value["valid_at"])
    return {
        **observation,
        "observed_at": sample["valid_at"],
        "measurement_kind": "predicted",
        "properties": {
            **props,
            **{k: v for k, v in sample.items() if k != "valid_at"},
            "forecast_valid_at": sample["valid_at"],
            "model_sample_at": observation["observed_at"],
        },
    }
