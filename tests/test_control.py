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
    first = client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar", "confirm": True}).json()
    second = client.post("/api/broadcast/program", json={"scene": "nyc", "field": "radar", "confirm": True}).json()
    assert (first["revision"], second["revision"]) == (1, 2)
    assert client.get("/api/broadcast/program").json()["scene"] == "nyc"
    reloaded = ProgramState(tmp_path / "program.json", clock=lambda: FIXED).snapshot()
    assert reloaded["scene"] == "nyc" and reloaded["revision"] == 2


def test_direct_cut_needs_explicit_confirmation(tmp_path):
    state, client = make(tmp_path)
    response = client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar"})
    assert response.status_code == 422 and "preview" in response.json()["detail"]
    assert state.snapshot()["revision"] == 0  # nothing changed on air
    ok = client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar", "confirm": True})
    assert ok.status_code == 200 and ok.json()["scene"] == "mia"


def test_rejects_bad_identifiers(tmp_path):
    _, client = make(tmp_path)
    response = client.post("/api/broadcast/program", json={"scene": "../x", "field": "radar", "confirm": True})
    assert response.status_code == 422


def test_corrupt_saved_state_starts_unset(tmp_path):
    (tmp_path / "program.json").write_text("{not json", encoding="utf-8")
    assert ProgramState(tmp_path / "program.json").snapshot()["revision"] == 0


def test_corrupt_saved_state_is_reported_and_quarantined(tmp_path):
    path = tmp_path / "program.json"
    path.write_text("{not json", encoding="utf-8")
    snapshot = ProgramState(path).snapshot()
    assert snapshot["persistence"]["recovered_from"]
    assert (tmp_path / "program.json.corrupt").exists() and not path.exists()


def test_startup_recovery_warning_clears_after_a_successful_save(tmp_path):
    path = tmp_path / "program.json"
    path.write_text("{not json", encoding="utf-8")
    state = ProgramState(path, clock=lambda: FIXED)
    client = TestClient(create_app(program=state))
    first = client.get("/api/broadcast/program").json()
    assert first["revision"] == 0 and first["persistence"]["ok"] is True and first["persistence"]["recovered_from"]
    taken = client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar", "confirm": True}).json()
    assert taken["persistence"]["recovered_from"] is None
    assert client.get("/api/broadcast/program").json()["persistence"]["recovered_from"] is None


def test_failed_save_is_reported_not_silent(tmp_path, monkeypatch):
    state, client = make(tmp_path)
    assert client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar", "confirm": True}).json()["persistence"]["ok"]

    def boom(self, target):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.replace", boom)
    body = client.post("/api/broadcast/program", json={"scene": "nyc", "field": "radar", "confirm": True}).json()
    assert body["scene"] == "nyc"  # the live program still changes
    assert body["persistence"]["ok"] is False and "disk full" in body["persistence"]["error"]
    assert client.get("/api/broadcast/program").json()["persistence"]["ok"] is False
    assert not [p for p in tmp_path.iterdir() if p.name not in {"program.json"}]  # no leaked temp files
    monkeypatch.undo()
    assert client.post("/api/broadcast/program", json={"scene": "chi", "field": "radar", "confirm": True}).json()["persistence"]["ok"]


def test_token_required_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHGLASS_CONTROL_TOKEN", "s3cret")
    _, client = make(tmp_path)
    body = {"scene": "mia", "field": "radar"}
    assert client.post("/api/broadcast/program", json={**body, "confirm": True}).status_code == 401
    assert client.post("/api/broadcast/program", json={**body, "confirm": True}, headers={"X-Control-Token": "no"}).status_code == 401
    assert client.post("/api/broadcast/program", json={**body, "confirm": True}, headers={"X-Control-Token": "s3cret"}).status_code == 200
    assert client.get("/api/broadcast/program").status_code == 200


def test_remote_client_refused_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("EARTHGLASS_CONTROL_TOKEN", raising=False)
    state = ProgramState(tmp_path / "program.json")
    client = TestClient(create_app(program=state), client=("203.0.113.9", 5000))
    response = client.post("/api/broadcast/program", json={"scene": "mia", "field": "radar", "confirm": True})
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
