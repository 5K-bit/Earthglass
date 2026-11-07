import pytest


@pytest.fixture(autouse=True)
def no_background_weather_refresh(monkeypatch):
    """Tests must never start the GFS scheduler, which would download from NOAA."""

    monkeypatch.setenv("EARTHGLASS_WEATHER_REFRESH_MINUTES", "0")
