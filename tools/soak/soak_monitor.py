"""Soak-test monitor for a running EarthGlass API.

Polls the endpoints that matter for a broadcast, once per interval, and appends one JSON line per
sample to ``samples.jsonl`` (flushed every time, so a crash loses nothing). With
``--restart-every-minutes`` it also restarts the API container on a schedule and checks that the
on-air shot survives. Standard library only; it sends no data anywhere except to the base URL.

    python tools/soak/soak_monitor.py --base http://127.0.0.1:8080 --hours 8 --out soak-run

Summarise with ``tools/soak/soak_report.py``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINTS = {
    "health": "/health",
    "program": "/api/broadcast/program",
    "radar": "/api/weather/radar",
    "alerts": "/api/layers/weather-alerts/features",
    "gfs": "/api/weather/layers",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch(base: str, path: str, timeout: float) -> dict:
    """One GET. Always returns a dict: ok, status, ms, and the parsed body when it is JSON."""

    started = time.monotonic()
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "ms": round((time.monotonic() - started) * 1000), "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001 - any failure is a data point
        return {"ok": False, "status": None, "ms": round((time.monotonic() - started) * 1000), "error": f"{type(exc).__name__}: {exc}"}
    result = {"ok": 200 <= status < 300, "status": status, "ms": round((time.monotonic() - started) * 1000)}
    try:
        result["body"] = json.loads(raw)
    except ValueError:
        result["body"] = None
    return result


def summarise(samples: dict[str, dict], at: datetime) -> dict:
    """Reduce the raw replies to the few facts the report needs."""

    facts: dict = {}
    program = (samples["program"].get("body") or {}) if samples["program"]["ok"] else {}
    facts["revision"] = program.get("revision")
    facts["scene"] = program.get("scene")
    facts["field"] = program.get("field")
    persistence = program.get("persistence") or {}
    facts["persistence_ok"] = persistence.get("ok") if program else None
    facts["recovered_from"] = persistence.get("recovered_from") if program else None

    radar = (samples["radar"].get("body") or {}) if samples["radar"]["ok"] else {}
    facts["radar_stale"] = radar.get("stale") if radar else None
    facts["radar_observation_age_s"] = radar.get("observation_age_seconds") if radar else None
    facts["radar_degraded"] = (radar.get("status") == "degraded") if radar else None

    alerts = (samples["alerts"].get("body") or {}) if samples["alerts"]["ok"] else {}
    metadata = alerts.get("metadata") or {}
    facts["alerts_stale"] = (metadata.get("cache") or {}).get("stale") if alerts else None
    retrieved = parse((metadata.get("source") or {}).get("retrieved_at"))
    facts["alerts_retrieval_age_s"] = round((at - retrieved).total_seconds()) if retrieved else None
    facts["alerts_count"] = len(alerts.get("features") or []) if alerts else None

    layers = samples["gfs"].get("body") if samples["gfs"]["ok"] else None
    if isinstance(layers, list):
        ages = []
        for layer in layers:
            cycle = parse(((layer.get("metadata") or {}).get("cycle")))
            ages.append(round((at - cycle).total_seconds() / 3600, 2) if cycle else None)
        facts["gfs_missing"] = sum(1 for age in ages if age is None)
        known = [age for age in ages if age is not None]
        facts["gfs_oldest_cycle_age_h"] = max(known) if known else None
        facts["gfs_errors"] = [layer.get("error") for layer in layers if layer.get("error")]
    return facts


def memory_mb(container: str | None) -> float | None:
    if not container:
        return None
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip().split("/")[0].strip()
    except Exception:  # noqa: BLE001
        return None
    for unit, scale in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024)):
        if out.endswith(unit):
            try:
                return round(float(out[: -len(unit)]) * scale, 1)
            except ValueError:
                return None
    return None


def restart_drill(base: str, compose_dir: str, service: str, timeout: float) -> dict:
    """Restart the API and check it comes back with the same on-air shot."""

    before = fetch(base, ENDPOINTS["program"], timeout)
    before_body = before.get("body") or {}
    started = time.monotonic()
    try:
        subprocess.run(["docker", "compose", "restart", service], cwd=compose_dir, capture_output=True, timeout=180, check=True)
    except Exception as exc:  # noqa: BLE001
        return {"drill": "restart", "ok": False, "error": f"restart failed: {exc}"}
    recovered_after = None
    after_body: dict = {}
    while time.monotonic() - started < 180:
        reply = fetch(base, ENDPOINTS["program"], timeout)
        if reply["ok"]:
            recovered_after = round(time.monotonic() - started, 1)
            after_body = reply.get("body") or {}
            break
        time.sleep(2)
    same = all(before_body.get(key) == after_body.get(key) for key in ("scene", "field", "revision"))
    return {
        "drill": "restart", "ok": recovered_after is not None and same,
        "recovered_after_s": recovered_after, "same_shot": same,
        "before": {k: before_body.get(k) for k in ("scene", "field", "revision")},
        "after": {k: after_body.get(k) for k in ("scene", "field", "revision")},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8080", help="API base URL (default %(default)s)")
    parser.add_argument("--hours", type=float, default=8.0, help="how long to run (default %(default)s)")
    parser.add_argument("--interval", type=float, default=15.0, help="seconds between samples (default %(default)s)")
    parser.add_argument("--timeout", type=float, default=10.0, help="per-request timeout in seconds")
    parser.add_argument("--out", default="soak-run", help="output directory (default %(default)s)")
    parser.add_argument("--container", default=None, help="docker container name to sample memory from")
    parser.add_argument("--compose-dir", default=".", help="directory with docker-compose.yml (for restart drills)")
    parser.add_argument("--service", default="api", help="compose service to restart in drills")
    parser.add_argument("--restart-every-minutes", type=float, default=0.0, help="restart drill period; 0 disables")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "started_at": iso(now()), "base": args.base, "hours": args.hours, "interval_s": args.interval,
        "restart_every_minutes": args.restart_every_minutes, "container": args.container,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    deadline = time.monotonic() + args.hours * 3600
    next_drill = time.monotonic() + args.restart_every_minutes * 60 if args.restart_every_minutes > 0 else None
    count = 0
    print(f"soak monitor: {args.base} for {args.hours} h, every {args.interval} s -> {out}/samples.jsonl", flush=True)
    try:
        with (out / "samples.jsonl").open("a", encoding="utf-8") as log:
            while time.monotonic() < deadline:
                cycle_started = time.monotonic()
                at = now()
                replies = {name: fetch(args.base, path, args.timeout) for name, path in ENDPOINTS.items()}
                line = {
                    "t": iso(at), "type": "sample",
                    "up": {name: reply["ok"] for name, reply in replies.items()},
                    "ms": {name: reply["ms"] for name, reply in replies.items()},
                    "errors": {name: reply["error"] for name, reply in replies.items() if reply.get("error")},
                    "facts": summarise(replies, at),
                    "memory_mb": memory_mb(args.container) if count % 20 == 0 else None,
                }
                log.write(json.dumps(line) + "\n")
                log.flush()
                count += 1
                if next_drill is not None and time.monotonic() >= next_drill:
                    drill = restart_drill(args.base, args.compose_dir, args.service, args.timeout)
                    drill.update({"t": iso(now()), "type": "drill"})
                    log.write(json.dumps(drill) + "\n")
                    log.flush()
                    print("drill:", drill, flush=True)
                    next_drill = time.monotonic() + args.restart_every_minutes * 60
                time.sleep(max(0.0, args.interval - (time.monotonic() - cycle_started)))
    except KeyboardInterrupt:
        print("stopped early", flush=True)
    finally:
        (out / "meta.json").write_text(json.dumps({**meta, "ended_at": iso(now()), "samples": count}, indent=2), encoding="utf-8")
    print(f"done: {count} samples", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
