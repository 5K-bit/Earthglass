from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from earthglass.weather.api import WeatherService


def test_offline_catalog_and_assets_are_instance_scoped(tmp_path):
    first = WeatherService(tmp_path / "first", lambda: True)
    second = WeatherService(tmp_path / "second", lambda: True)
    (first.root / "latest").mkdir(parents=True)
    (first.root / "latest" / "temperature.png").write_bytes(b"cached image")
    try:
        for service, expected in ((first, 200), (second, 404)):
            app = FastAPI()
            app.include_router(service.router())
            with TestClient(app) as client:
                catalog = client.get("/api/weather/layers").json()
                assert len(catalog) == 6
                assert all(layer["offline"] for layer in catalog)
                assert client.get("/weather/gfs/latest/temperature.png").status_code == expected
                assert client.get("/weather/gfs/latest/private.json").status_code == 404
                assert client.post("/api/weather/layers/temperature/refresh").status_code == 409
                assert client.post("/api/weather/layers/unknown/refresh").status_code == 404
    finally:
        first.close()
        second.close()


def test_concurrent_refresh_shares_one_worker_and_shutdown_rejects(tmp_path, monkeypatch):
    # refresh_layers reaches the GRIB decoder, so it needs the optional weather stack
    # (requirements/weather.in). Every other weather test runs without it.
    pytest.importorskip("xarray", reason="optional GFS weather stack is not installed")
    from earthglass.weather.gfs import refresh_layers
    entered, release = Event(), Event()
    calls = []
    def fetch(layer):
        calls.append(layer)
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(refresh_layers, "refresh_layer", fetch)
    service = WeatherService(tmp_path, lambda: False)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: service.refresh("temperature"), range(8)))
        assert entered.wait(2)
        assert all(result["status"] == "refreshing" for result in results)
        assert calls == ["temperature"]
    finally:
        release.set()
        service.close()
    with pytest.raises(HTTPException) as error:
        service.refresh("temperature")
    assert error.value.status_code == 409
