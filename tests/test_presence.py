from datetime import datetime, timedelta, timezone
import json
import pytest
from fastapi.testclient import TestClient
from earthglass.presence.store import PresenceStore, PresenceDenied
from earthglass.presence.api import build_presence_app
from earthglass.presence.models import (
    DeviceRegistration,
    DeviceUpdate,
    PresenceSettings,
    ViewerRegistration,
    Position,
)

NOW = datetime.now(timezone.utc)
OWNER = {"kind": "owner", "subject": "local-operator", "scope": {}}


@pytest.fixture
def store(tmp_path):
    value = PresenceStore(tmp_path / "private" / "presence.sqlite3")
    yield value
    value.close()


def device(store, ident="phone", traccar="42", enabled=True, days=30):
    return store.register(
        DeviceRegistration(
            device_id=ident,
            label="Fixture phone",
            traccar_id=traccar,
            tracking_enabled=enabled,
            retention_days=days,
        )
    )


def position(at=NOW, lat=40.1):
    return Position(
        latitude=lat,
        longitude=-73.9,
        accuracy_m=8,
        battery_percent=71,
        speed_mps=0,
        recorded_at=at,
    )


def client(store, owner=False, token=None):
    app = build_presence_app(store, owner_auth=(lambda _: True) if owner else None)
    return TestClient(
        app,
        base_url="https://presence.test",
        headers={"Authorization": "Bearer " + token} if token else {},
    )


def test_default_disabled_and_unknown_devices_rejected(store):
    assert store.settings()["enabled"] is False
    with pytest.raises(PresenceDenied):
        store.ingest("unknown", position())
    device(store)
    with pytest.raises(PresenceDenied):
        store.ingest("phone", position())
    assert not store.list_current(OWNER)[0]["position"]


def test_private_api_denies_anonymous_and_plaintext(store):
    with client(store) as api:
        assert api.get("/v2/presence").status_code == 401
        assert api.post("/v2/presence/devices", json={}).status_code == 401
    with TestClient(build_presence_app(store), base_url="http://presence.test") as api:
        assert api.get("/v2/presence").status_code == 403


def test_device_credentials_are_bound_to_one_tracker(store):
    registered = device(store)
    store.configure(PresenceSettings(enabled=True))
    payload = {
        "position": {
            "deviceId": 99,
            "valid": True,
            "latitude": 40,
            "longitude": -74,
            "fixTime": NOW.isoformat(),
            "speed": 10,
            "course": 90,
            "attributes": {"batteryLevel": 55},
        }
    }
    with client(store, token=registered["token"]) as api:
        assert api.get("/v2/presence").status_code == 403
        assert api.post("/v2/presence/ingest/traccar", json=payload).status_code == 422
        payload["position"]["deviceId"] = 42
        assert api.post("/v2/presence/ingest/traccar", json=payload).status_code == 200
        assert api.get("/v2/presence/settings").status_code == 403
    assert store.current("phone", OWNER)["position"]["speed_mps"] == pytest.approx(
        5.14444444
    )
    assert registered["token"] not in json.dumps(store.audit_entries())


def test_viewer_acl_redacts_battery_and_forbids_admin_history(store):
    device(store)
    device(store, "other", "43")
    store.configure(PresenceSettings(enabled=True))
    store.ingest("phone", position())
    credentials = store.add_viewer(
        ViewerRegistration(label="Family fixture", devices=["phone"])
    )
    with client(store, token=credentials["token"]) as api:
        response = api.get("/v2/presence")
        assert response.status_code == 200
        data = response.json()["data"]
        assert (
            len(data) == 1
            and "battery_percent" not in data[0]["position"]
            and "owner_id" not in data[0]["position"]
        )
        assert response.headers["cache-control"] == "no-store, private"
        for path in [
            "/v2/presence/other",
            "/v2/presence/phone/history",
            "/v2/presence/devices",
            "/v2/presence/audit",
        ]:
            assert api.get(path).status_code == 403
        assert (
            api.patch(
                "/v2/presence/devices/phone", json={"tracking_enabled": False}
            ).status_code
            == 403
        )
        assert api.delete("/v2/presence/devices/phone").status_code == 403
        assert api.post("/v2/presence/ingest/traccar", json={}).status_code == 403
    store.revoke(credentials["credential_id"])
    with client(store, token=credentials["token"]) as api:
        assert api.get("/v2/presence").status_code == 401


def test_history_pagination_duplicate_and_out_of_order(store):
    device(store)
    store.configure(PresenceSettings(enabled=True))
    for offset in [0, -30, -60, -30]:
        store.ingest(
            "phone", position(NOW + timedelta(seconds=offset), 40.1 + offset / 1000)
        )
    assert (
        datetime.fromisoformat(store.current("phone", OWNER)["position"]["recorded_at"])
        == NOW
    )
    result = store.history("phone", OWNER, NOW - timedelta(hours=1), NOW, limit=2)
    assert len(result["data"]) == 2 and result["next_cursor"]
    rest = store.history(
        "phone", OWNER, NOW - timedelta(hours=1), NOW, cursor=result["next_cursor"]
    )
    assert len(rest["data"]) == 1
    historical = store.current("phone", OWNER, NOW - timedelta(seconds=45))
    assert datetime.fromisoformat(
        historical["position"]["recorded_at"]
    ) == NOW - timedelta(seconds=60)


def test_retention_disabled_and_revoke_device(store):
    credential = device(store)
    store.configure(PresenceSettings(enabled=True))
    store.ingest("phone", position())
    store.update("phone", DeviceUpdate(retention_days=0))
    assert store.history("phone", OWNER, NOW - timedelta(days=1), NOW)["data"] == []
    assert store.current("phone", OWNER)["position"]
    store.ingest("phone", position(NOW + timedelta(seconds=1)))
    assert (
        store.history(
            "phone", OWNER, NOW - timedelta(days=1), NOW + timedelta(minutes=1)
        )["data"]
        == []
    )
    store.delete("phone")
    assert store.authenticate(credential["token"]) is None
    assert store.list_current(OWNER) == []


def test_future_positions_invalid_fixes_and_disabled_device(store):
    device(store, enabled=False)
    store.configure(PresenceSettings(enabled=True))
    with pytest.raises(PresenceDenied):
        store.ingest("phone", position())
    store.update("phone", DeviceUpdate(tracking_enabled=True))
    with pytest.raises(ValueError):
        store.ingest("phone", position(NOW + timedelta(hours=1)))
    with pytest.raises(ValueError):
        store.ingest("phone", position(NOW - timedelta(days=31)))
    with pytest.raises(ValueError):
        Position(latitude=float("nan"), longitude=0, recorded_at=NOW)
    with pytest.raises(ValueError):
        Position(latitude=0, longitude=0, recorded_at=datetime.now())


def test_status_uses_fix_age_not_recent_receipt(store):
    device(store)
    store.configure(PresenceSettings(enabled=True))
    store.ingest("phone", position(NOW - timedelta(minutes=20)))
    assert store.current("phone", OWNER)["status"] == "stale"


def test_credentials_rotation_and_no_plaintext_disk(store, tmp_path):
    old = device(store)
    new = store.rotate_device("phone")
    assert store.authenticate(old["token"]) is None
    assert store.authenticate(new["token"])["kind"] == "device"
    raw = (tmp_path / "private" / "presence.sqlite3").read_bytes()
    assert old["token"].encode() not in raw and new["token"].encode() not in raw


def test_body_bounds_and_rate_limit(store):
    with client(store, owner=True) as api:
        assert (
            api.post("/v2/presence/ingest/traccar", content=b"x" * 32769).status_code
            == 413
        )
    assert all(store.rate_limit("test", 2) for _ in range(2))
    assert not store.rate_limit("test", 2)


def test_private_gateway_serves_bundled_viewer_without_public_data_routes(tmp_path):
    from earthglass.presence.gateway import build_presence_gateway
    from earthglass.presence.store import PresenceStore

    store = PresenceStore(tmp_path / "private.sqlite3")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "presence.html").write_text(
        "<h1>Private viewer fixture</h1>", encoding="utf-8"
    )
    try:
        app = build_presence_gateway(store, assets)
        with TestClient(app, base_url="https://presence.example") as client:
            page = client.get("/")
            assert (
                page.status_code == 200
                and "connect-src 'self'" in page.headers["content-security-policy"]
            )
            assert client.get("/private/v2/presence").status_code == 401
            assert client.get("/api/v2/observations").status_code == 404
        with TestClient(app, base_url="http://presence.example") as client:
            assert client.get("/").status_code == 403
    finally:
        store.close()
