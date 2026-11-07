"""Turn a soak run (``samples.jsonl``) into a plain-language reliability report.

    python tools/soak/soak_report.py soak-run > soak-run/REPORT.md

Reports facts only: availability, outages, data freshness, latency, memory, restart drills. It does
not grade the result; the station decides what is acceptable.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

NAMES = ("health", "program", "radar", "alerts", "gfs")


def load(directory: Path) -> tuple[dict, list[dict], list[dict]]:
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    samples, drills = [], []
    for line in (directory / "samples.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        (drills if record.get("type") == "drill" else samples).append(record)
    return meta, samples, drills


def when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def runs(samples: list[dict], predicate) -> list[tuple[str, str, int]]:
    """Consecutive stretches where predicate(sample) is true: (start, end, sample count)."""

    found, start, last, n = [], None, None, 0
    for sample in samples:
        if predicate(sample):
            start = start or sample["t"]
            last, n = sample["t"], n + 1
        elif start:
            found.append((start, last, n))
            start, n = None, 0
    if start:
        found.append((start, last, n))
    return found


def fmt_runs(items: list[tuple[str, str, int]], interval: float) -> str:
    if not items:
        return "none"
    rows = []
    for start, end, n in items[:20]:
        seconds = max((when(end) - when(start)).total_seconds(), 0) + interval
        rows.append(f"{start} to {end} (about {round(seconds)} s, {n} samples)")
    more = f"; and {len(items) - 20} more" if len(items) > 20 else ""
    return "; ".join(rows) + more


def report(directory: Path) -> str:
    meta, samples, drills = load(directory)
    interval = float(meta.get("interval_s", 15))
    out = ["# EarthGlass soak test report", ""]
    if not samples:
        return "\n".join(out + ["No samples were recorded."])
    first, last = samples[0]["t"], samples[-1]["t"]
    hours = (when(last) - when(first)).total_seconds() / 3600
    out += [
        f"- Target: `{meta['base']}`; sampled every {interval:g} s",
        f"- Run: {first} to {last} ({hours:.2f} h, {len(samples)} samples; planned {meta['hours']} h)",
        "",
        "## Availability",
        "",
        "| Endpoint | Up | Failed samples | Median ms | p95 ms | Max ms |",
        "|---|---|---|---|---|---|",
    ]
    for name in NAMES:
        up = [s["up"].get(name, False) for s in samples]
        times = [s["ms"][name] for s in samples if s["up"].get(name) and name in s["ms"]]
        failed = up.count(False)
        out.append(
            f"| {name} | {100 * (len(up) - failed) / len(up):.2f}% | {failed} | "
            f"{percentile(times, 0.5) or '-'} | {percentile(times, 0.95) or '-'} | {max(times) if times else '-'} |"
        )
    out += ["", "### API outages (health endpoint down)", "", fmt_runs(runs(samples, lambda s: not s["up"].get("health", False)), interval), ""]

    out += ["## Data freshness", ""]
    stale_radar = runs(samples, lambda s: s["facts"].get("radar_stale") is True)
    no_radar = runs(samples, lambda s: s["up"].get("radar") is False)
    ages = [s["facts"]["radar_observation_age_s"] for s in samples if s["facts"].get("radar_observation_age_s") is not None]
    out += [
        f"- Radar marked stale: {fmt_runs(stale_radar, interval)}",
        f"- Radar endpoint unavailable: {fmt_runs(no_radar, interval)}",
        f"- Radar observation age: median {percentile(ages, 0.5)} s, p95 {percentile(ages, 0.95)} s, max {max(ages) if ages else '-'} s",
    ]
    stale_alerts = runs(samples, lambda s: s["facts"].get("alerts_stale") is True)
    alert_ages = [s["facts"]["alerts_retrieval_age_s"] for s in samples if s["facts"].get("alerts_retrieval_age_s") is not None]
    out += [
        f"- NWS alert feed marked stale by the server: {fmt_runs(stale_alerts, interval)}",
        f"- NWS retrieval age: median {percentile(alert_ages, 0.5)} s, p95 {percentile(alert_ages, 0.95)} s, max {max(alert_ages) if alert_ages else '-'} s",
    ]
    cycle_ages = [s["facts"]["gfs_oldest_cycle_age_h"] for s in samples if s["facts"].get("gfs_oldest_cycle_age_h") is not None]
    missing = max((s["facts"].get("gfs_missing") or 0) for s in samples)
    gfs_errors = sorted({e for s in samples for e in (s["facts"].get("gfs_errors") or [])})
    out += [
        f"- Oldest GFS cycle on screen: max {max(cycle_ages) if cycle_ages else '-'} h (the studio calls a cycle older than 10 h stale); most layers missing at once: {missing}",
        f"- GFS refresh errors reported: {', '.join(gfs_errors) if gfs_errors else 'none'}",
        "",
        "## Program state",
        "",
    ]
    revisions = [(s["t"], s["facts"]["revision"]) for s in samples if s["facts"].get("revision") is not None]
    drops = [(t, a, b) for (_, a), (t, b) in zip(revisions, revisions[1:]) if b < a]
    save_failures = runs(samples, lambda s: s["facts"].get("persistence_ok") is False)
    recovered = {s["facts"]["recovered_from"] for s in samples if s["facts"].get("recovered_from")}
    out += [
        f"- Revision went backwards (state lost or reset): {'; '.join(f'{t}: {a} to {b}' for t, a, b in drops) if drops else 'never'}",
        f"- On-air state could not be saved: {fmt_runs(save_failures, interval)}",
        f"- Startup recovery from unreadable state: {', '.join(sorted(recovered)) if recovered else 'none'}",
        "",
    ]
    memory = [(s["t"], s["memory_mb"]) for s in samples if s.get("memory_mb") is not None]
    if memory:
        values = [m for _, m in memory]
        out += ["## Memory (API container)", "", f"- First {values[0]} MiB, last {values[-1]} MiB, max {max(values)} MiB over {len(values)} samples", ""]
    if drills:
        out += ["## Restart drills", "", "| Time | Recovered after | Same shot | Result |", "|---|---|---|---|"]
        for drill in drills:
            out.append(f"| {drill['t']} | {drill.get('recovered_after_s', '-')} s | {drill.get('same_shot', '-')} | {'pass' if drill['ok'] else 'FAIL'} |")
        out += ["", f"{sum(1 for d in drills if d['ok'])} of {len(drills)} drills passed.", ""]
    out += [
        "## Limits of this report",
        "",
        "- It measures the API from the machine that runs it, not what OBS rendered. A frozen picture in OBS would not appear here.",
        "- It reports freshness flags and ages; it does not judge whether the weather content is correct.",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: soak_report.py <run directory>")
    print(report(Path(sys.argv[1])))
