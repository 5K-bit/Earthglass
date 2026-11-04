from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from earthglass.radar import RadarService, latest_observation_time, MAX_OBSERVATION_AGE_SECONDS
from earthglass.web.app import create_app

NOW = datetime(2026, 11, 4, 18, 45, tzinfo=timezone.utc)
PNG = b"\x89PNG\r\n\x1a\nfake"
CAPS = (
    b'<Layer><Dimension name="time" default="2026-11-04T18:41:55Z" units="ISO8601">'
    b"2026-11-04T18:36:01.000Z,2026-11-04T18:41:55.000Z,2026-11-04T18:40:03.000Z</Dimension></Layer>"
)


def fetcher(calls):
    def fetch(url, timeout):
        calls.append(url)
        return CAPS if "GetCapabilities" in url else PNG
    return fetch


def test_latest_time_is_newest_advertised_frame():
    assert latest_observation_time(CAPS) == "2026-11-04T18:41:55Z"
    with pytest.raises(ValueError):
        latest_observation_time(b"<none/>")


def test_status_reports_observation_time_and_requests_that_exact_frame(tmp_path):
    calls = []
    service = RadarService(tmp_path, fetcher=fetcher(calls), clock=lambda: NOW)
    status = service.status()
    assert status["observed_at"] == "2026-11-04T18:41:55Z"
    assert status["observation_age_seconds"] == 185
    assert status["stale"] is False and status["status"] == "ready"
    assert "time=2026-11-04T18:41:55Z" in calls[-1]
    assert status["coverage"] == "CONUS only"


def test_frame_is_reused_until_refresh_interval(tmp_path):
    calls = []
    clock = {"now": NOW}
    service = RadarService(tmp_path, fetcher=fetcher(calls), clock=lambda: clock["now"])
    service.status()
    count = len(calls)
    clock["now"] = NOW + timedelta(seconds=60)
    service.status()
    assert len(calls) == count
    clock["now"] = NOW + timedelta(seconds=130)
    service.status()
    assert len(calls) > count


def test_outage_serves_retained_frame_and_goes_stale(tmp_path):
    clock = {"now": NOW}
    service = RadarService(tmp_path, fetcher=fetcher([]), clock=lambda: clock["now"])
    service.status()

    def down(url, timeout):
        raise RuntimeError("down")
    service.fetcher = down
    clock["now"] = NOW + timedelta(seconds=300)
    status = service.status()
    assert status["status"] == "degraded" and "down" in status["error"]
    assert status["stale"] is False
    clock["now"] = NOW + timedelta(seconds=MAX_OBSERVATION_AGE_SECONDS + 600)
    assert service.status()["stale"] is True


def test_outage_without_retained_frame_is_503(tmp_path):
    def down(url, timeout):
        raise RuntimeError("down")
    api = TestClient(create_app(radar=RadarService(tmp_path, fetcher=down, clock=lambda: NOW)))
    assert api.get("/api/weather/radar").status_code == 503
    assert api.get("/weather/radar/latest.png").status_code == 503


def test_non_png_response_is_rejected(tmp_path):
    def fetch(url, timeout):
        return CAPS if "GetCapabilities" in url else b"<ServiceException/>"
    api = TestClient(create_app(radar=RadarService(tmp_path, fetcher=fetch, clock=lambda: NOW)))
    assert api.get("/api/weather/radar").status_code == 503


def test_http_api_serves_metadata_and_image(tmp_path):
    api = TestClient(create_app(radar=RadarService(tmp_path, fetcher=fetcher([]), clock=lambda: NOW)))
    assert api.get("/api/weather/radar").json()["image"] == "/weather/radar/latest.png"
    image = api.get("/weather/radar/latest.png")
    assert image.status_code == 200 and image.content == PNG
