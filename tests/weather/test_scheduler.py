from datetime import datetime, timedelta, timezone
from threading import Event

from earthglass.weather.api import WeatherService
from earthglass.weather.gfs.layers import get_layer_definitions

NOW = datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)


class Meta:
    def __init__(self, cycle):
        self.cycle = cycle


def patch_metadata(monkeypatch, cycles):
    monkeypatch.setattr(
        "earthglass.weather.api.read_layer_metadata",
        lambda layer: Meta(cycles[layer]) if cycles.get(layer) else None,
    )


def test_missing_and_old_cycles_are_due_but_recent_ones_are_not(tmp_path, monkeypatch):
    ids = [str(d["id"]) for d in get_layer_definitions()]
    cycles = {ids[0]: NOW - timedelta(hours=9), ids[1]: NOW - timedelta(hours=3), ids[2]: None}
    for other in ids[3:]:
        cycles[other] = NOW - timedelta(hours=5, minutes=59)
    patch_metadata(monkeypatch, cycles)
    service = WeatherService(tmp_path, lambda: False)
    try:
        assert service.due_layers(NOW) == [ids[0], ids[2]]
    finally:
        service.close()


def test_refresh_due_requests_only_due_layers_and_never_raises_when_offline(tmp_path, monkeypatch):
    ids = [str(d["id"]) for d in get_layer_definitions()]
    patch_metadata(monkeypatch, {layer: (NOW - timedelta(hours=8)) for layer in ids})
    requested = []
    service = WeatherService(tmp_path, lambda: False)
    monkeypatch.setattr(service, "refresh", lambda layer: requested.append(layer) or {"status": "refreshing"})
    try:
        assert service.refresh_due(NOW) == ids and requested == ids
    finally:
        service.close()
    offline = WeatherService(tmp_path / "off", lambda: True)
    try:
        assert offline.refresh_due(NOW) == []  # offline: refresh raises 409 inside, handled
    finally:
        offline.close()


def test_scheduler_runs_immediately_repeats_and_stops_on_close(tmp_path, monkeypatch):
    service = WeatherService(tmp_path, lambda: False)
    ran = Event()
    count = {"n": 0}

    def fake_refresh_due(now=None):
        count["n"] += 1
        if count["n"] >= 2:
            ran.set()
        return []

    monkeypatch.setattr(service, "refresh_due", fake_refresh_due)
    service.start_scheduler(0.05)
    assert ran.wait(3)
    service.close()
    after = count["n"]
    assert not service._scheduler.is_alive()
    assert count["n"] == after


def test_scheduler_survives_a_failing_check_and_zero_interval_disables_it(tmp_path, monkeypatch):
    service = WeatherService(tmp_path, lambda: False)
    calls = Event()
    count = {"n": 0}

    def boom(now=None):
        count["n"] += 1
        if count["n"] >= 2:
            calls.set()
        raise RuntimeError("disk error")

    monkeypatch.setattr(service, "refresh_due", boom)
    service.start_scheduler(0.05)
    assert calls.wait(3) and service._scheduler.is_alive()
    service.close()
    other = WeatherService(tmp_path / "x", lambda: False)
    other.start_scheduler(0)
    assert other._scheduler is None
    other.close()
