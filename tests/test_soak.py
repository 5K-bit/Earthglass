import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tools" / "soak"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


monitor = load("soak_monitor")
reporter = load("soak_report")

AT = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)


def reply(body, ok=True):
    return {"ok": ok, "status": 200 if ok else None, "ms": 5, "body": body}


def test_summarise_extracts_freshness_and_state_facts():
    replies = {
        "health": reply({"status": "ok"}),
        "program": reply({"scene": "nyc", "field": "radar", "revision": 4, "persistence": {"ok": False, "recovered_from": None}}),
        "radar": reply({"stale": True, "observation_age_seconds": 1200, "status": "degraded"}),
        "alerts": reply({"features": [1, 2], "metadata": {"cache": {"stale": False}, "source": {"retrieved_at": "2026-11-07T02:59:00Z"}}}),
        "gfs": reply([{"id": "a", "metadata": {"cycle": "2026-11-07T00:00:00Z"}}, {"id": "b", "metadata": None, "error": "boom"}]),
    }
    facts = monitor.summarise(replies, AT)
    assert facts["revision"] == 4 and facts["persistence_ok"] is False
    assert facts["radar_stale"] is True and facts["radar_degraded"] is True
    assert facts["alerts_stale"] is False and facts["alerts_retrieval_age_s"] == 60 and facts["alerts_count"] == 2
    assert facts["gfs_oldest_cycle_age_h"] == 3.0 and facts["gfs_missing"] == 1 and facts["gfs_errors"] == ["boom"]


def test_summarise_survives_a_dead_api():
    down = {"ok": False, "status": None, "ms": 10, "error": "URLError"}
    facts = monitor.summarise({name: down for name in monitor.ENDPOINTS}, AT)
    assert facts["revision"] is None and facts["radar_stale"] is None and facts["alerts_stale"] is None


def sample(t, up=True, revision=1, stale=False, persistence_ok=True):
    ok = {name: up for name in reporter.NAMES}
    return {
        "type": "sample", "t": t, "up": ok, "ms": {name: 10 for name in reporter.NAMES},
        "facts": {"revision": revision if up else None, "radar_stale": stale if up else None,
                  "persistence_ok": persistence_ok if up else None},
        "memory_mb": 100.0 if t.endswith(":00Z") else None,
    }


def test_report_finds_outages_stale_stretches_lost_state_and_drills(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"base": "http://x", "hours": 1, "interval_s": 15}), encoding="utf-8")
    lines = [
        sample("2026-11-07T03:00:00Z", revision=5),
        sample("2026-11-07T03:00:15Z", revision=5),
        sample("2026-11-07T03:00:30Z", up=False),
        sample("2026-11-07T03:00:45Z", up=False),
        sample("2026-11-07T03:01:00Z", revision=1, stale=True, persistence_ok=False),
        {"type": "drill", "t": "2026-11-07T03:02:00Z", "ok": True, "recovered_after_s": 6.5, "same_shot": True},
        {"type": "drill", "t": "2026-11-07T03:03:00Z", "ok": False, "recovered_after_s": None, "same_shot": False},
    ]
    (tmp_path / "samples.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    text = reporter.report(tmp_path)
    assert "5 samples" in text
    assert "2026-11-07T03:00:30Z to 2026-11-07T03:00:45Z" in text  # the outage
    assert "5 to 1" in text  # revision went backwards
    assert "Radar marked stale: 2026-11-07T03:01:00Z" in text
    assert "On-air state could not be saved: 2026-11-07T03:01:00Z" in text
    assert "1 of 2 drills passed" in text and "FAIL" in text
    assert "Limits of this report" in text


def test_report_handles_an_empty_run(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"base": "http://x", "hours": 1}), encoding="utf-8")
    (tmp_path / "samples.jsonl").write_text("", encoding="utf-8")
    assert "No samples" in reporter.report(tmp_path)
