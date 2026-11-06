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
    meta = api.get("/api/weather/radar").json()
    assert meta["image"] == "/weather/radar/frames/radar-20261104T184155Z.png"
    image = api.get(meta["image"])
    assert image.status_code == 200 and image.content == PNG
    assert "immutable" in image.headers["cache-control"]
    assert api.get("/weather/radar/latest.png").content == PNG


def test_each_frame_url_keeps_its_own_picture_after_a_newer_frame_arrives(tmp_path):
    caps = {"v": CAPS}
    pic = {"v": b"\x89PNGfirst"}
    clock = {"now": NOW}

    def fetch(url, timeout):
        return caps["v"] if "GetCapabilities" in url else pic["v"]

    service = RadarService(tmp_path, fetcher=fetch, clock=lambda: clock["now"])
    api = TestClient(create_app(radar=service))
    first = api.get("/api/weather/radar").json()
    caps["v"] = CAPS.replace(b"18:41:55", b"18:43:58")
    pic["v"] = b"\x89PNGsecond"
    clock["now"] = NOW + timedelta(seconds=130)
    second = api.get("/api/weather/radar").json()
    assert first["observed_at"] != second["observed_at"] and first["image"] != second["image"]
    # the older URL still returns the older picture, the newer URL the newer one
    assert api.get(first["image"]).content == b"\x89PNGfirst"
    assert api.get(second["image"]).content == b"\x89PNGsecond"


def test_same_observation_never_rewrites_its_frame(tmp_path):
    pic = {"v": b"\x89PNGone"}
    clock = {"now": NOW}

    def fetch(url, timeout):
        return CAPS if "GetCapabilities" in url else pic["v"]

    service = RadarService(tmp_path, fetcher=fetch, clock=lambda: clock["now"])
    api = TestClient(create_app(radar=service))
    url = api.get("/api/weather/radar").json()["image"]
    pic["v"] = b"\x89PNGother"
    clock["now"] = NOW + timedelta(seconds=130)
    api.get("/api/weather/radar")
    assert api.get(url).content == b"\x89PNGone"


def test_old_frames_are_pruned_and_bad_ids_refused(tmp_path):
    service = RadarService(tmp_path, fetcher=fetcher([]), clock=lambda: NOW)
    current = service.status()["frame_id"]
    frames = tmp_path / "frames"
    for n in range(10):
        (frames / f"radar-2026110{1 + n % 3}T0{n}0000Z.png").write_bytes(PNG)
    service._prune(current)
    assert len(list(frames.glob("radar-*.png"))) <= 7
    assert service.frame_path(current).is_file()
    api = TestClient(create_app(radar=service))
    assert api.get("/weather/radar/frames/..%2Fx.png").status_code == 404
    assert api.get("/weather/radar/frames/radar-19990101T000000Z.png").status_code == 404
