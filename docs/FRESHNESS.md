# Fresh, stale and unavailable: what EarthGlass reports

Everything below is reproducible without a network:

```bash
python -m pip install -e ".[dev]"
python tools/freshness_demo.py            # prints the table
python tools/freshness_demo.py --out docs/demo/freshness-transcript.md
```

The script starts the real FastAPI app on `127.0.0.1` with the real
`USGSEarthquakeProvider` and `FeatureCache`. Only the upstream fetcher and the
clock are replaced, using the fixed dataset in `docs/demo/usgs-fixture.json`
(3 labelled fixture earthquakes, not real events). Last output is saved in
[`docs/demo/freshness-transcript.md`](demo/freshness-transcript.md).

## States

| State | How a client sees it | Existing or new |
|---|---|---|
| **Fresh, live** | HTTP 200, `metadata.cache = {status: "live", stale: false}`, provider `ready` | Existing (`test_live_refresh_normalizes_validates_and_persists`) |
| **Fresh, from cache** | HTTP 200, `cache.status = "cache"`, `stale: false`, `age_seconds` ≤ refresh interval (300 s), no network call | Existing (`test_fresh_disk_cache_avoids_network`) |
| **Stale** (upstream failed, last valid data served) | HTTP 200, `cache.status = "cache"`, `stale: true`, `age_seconds`, provider `degraded`, `last_error` set | Existing (`test_failed_refresh_serves_explicitly_stale_cache`) |
| **Unavailable** (no valid cache, upstream failed) | HTTP 503, provider `unavailable`. Stale data is never presented as live | Existing (`test_failed_refresh_without_cache_is_unavailable`) |
| **Corrupt cache file** | Treated as no cache (503 if upstream is also down) | Existing (`test_corrupt_cache_is_ignored`); end-to-end row 7 of the transcript |
| **Aged cache, nobody asked** | `/api/providers/status` now reports `cache_stale: true` once the cache is older than the refresh interval | **New in this branch** (see below) |
| Concurrent refresh / cache write failure | One upstream call for six concurrent cold requests; fresh data kept when the disk write fails | Existing (`tests/test_refresh_concurrency.py`) |

## The one behavior change

`/api/providers/status` computed `cache_age_seconds` live but only updated
`cache_stale` as a side effect of a refresh. With nothing requesting data, a
cache three hours old was reported as `cache_stale: false`, `state: ready`.

Found by running the scenario replay, then confirmed in isolation. Fix: `status`
derives `cache_stale` from cache age (`earthglass/usgs.py`). Regression test
`test_status_reports_aged_cache_as_stale_without_a_request` fails without the fix
and passes with it.

## Remaining limits

- `state` still reads `ready` for an aged cache until a request triggers a
  refresh; only `cache_stale` and `cache_age_seconds` show the age. Whether
  `state` should change is a design decision, not made here.
- The replay covers the USGS earthquake provider only. Other providers
  (aviation, maritime, weather, transit) have their own freshness handling in
  `earthglass/spatial/` and `earthglass/weather/` and are not exercised here.
- The OBEOS Earth client has its own staleness rule in
  `obeos-earth/src/observationFreshness.ts` (per-layer TTLs). It is separate from
  the server's `cache.stale` flag and is not covered by the replay.
- No browser screenshot of the globe in each state yet.
