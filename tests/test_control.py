from datetime import datetime, timezone

from fastapi.testclient import TestClient

from earthglass.control import ProgramState
from earthglass.web.app import create_app

FIXED = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make(tmp_path):
    state = ProgramState(tmp_path / "program.json", clock=lambda: FIXED)
    return state, TestClient(create_app(program=state))


def test_starts_unset(tmp_path):
    _, client = make(tmp_path)
    body = client.get("/api/broadcast/program").json()
    assert body["scene"] is None and body["revision"] == 0


def test_update_bumps_revision_and_persists(tmp_path):
    state, client = make(tmp_path)
    first = client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar"}).json()
    second = client.post("/api/broadcast/program", json={"scene": "nyc", "field": "radar"}).json()
    assert (first["revision"], second["revision"]) == (1, 2)
    assert client.get("/api/broadcast/program").json()["scene"] == "nyc"
    reloaded = ProgramState(tmp_path / "program.json", clock=lambda: FIXED).snapshot()
    assert reloaded["scene"] == "nyc" and reloaded["revision"] == 2


def test_rejects_bad_identifiers(tmp_path):
    _, client = make(tmp_path)
    response = client.post("/api/broadcast/program", json={"scene": "../x", "field": "radar"})
    assert response.status_code == 422


def test_corrupt_saved_state_starts_unset(tmp_path):
    (tmp_path / "program.json").write_text("{not json", encoding="utf-8")
    assert ProgramState(tmp_path / "program.json").snapshot()["revision"] == 0


def test_token_required_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHGLASS_CONTROL_TOKEN", "s3cret")
    _, client = make(tmp_path)
    body = {"scene": "mia", "field": "radar"}
    assert client.post("/api/broadcast/program", json=body).status_code == 401
    assert client.post("/api/broadcast/program", json=body, headers={"X-Control-Token": "no"}).status_code == 401
    assert client.post("/api/broadcast/program", json=body, headers={"X-Control-Token": "s3cret"}).status_code == 200
    assert client.get("/api/broadcast/program").status_code == 200


def test_remote_client_refused_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("EARTHGLASS_CONTROL_TOKEN", raising=False)
    state = ProgramState(tmp_path / "program.json")
    client = TestClient(create_app(program=state), client=("203.0.113.9", 5000))
    response = client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar"})
    assert response.status_code == 403


def test_take_requires_matching_staged_shot(tmp_path):
    _, client = make(tmp_path)
    body = {"scene": "mia", "field": "radar"}
    assert client.post("/api/broadcast/take", json=body).status_code == 409
    staged = client.post("/api/broadcast/preview", json=body).json()
    assert staged["preview"] == body and staged["revision"] == 0
    assert client.get("/api/broadcast/program").json()["scene"] is None
    assert client.post("/api/broadcast/take", json={"scene": "nyc", "field": "radar"}).status_code == 409
    taken = client.post("/api/broadcast/take", json=body).json()
    assert taken["scene"] == "mia" and taken["revision"] == 1


def test_preview_and_take_are_protected(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHGLASS_CONTROL_TOKEN", "s3cret")
    _, client = make(tmp_path)
    body = {"scene": "mia", "field": "radar"}
    assert client.post("/api/broadcast/preview", json=body).status_code == 401
    assert client.post("/api/broadcast/take", json=body).status_code == 401
