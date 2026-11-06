# BES-1 pilot: EarthGlass

**Status:** Pilot proposal; no on-air or live-deployment approval is implied.  
**Canonical standard:** [BES-1 on OBEOS](https://github.com/5K-bit/O.B.E.O.S/blob/main/docs/standards/BES-1.md) (proposed in [OBEOS PR #16](https://github.com/5K-bit/O.B.E.O.S/pull/16); merge that PR before adopting this pilot).

## Existing architecture and invariant

The Python EarthGlass provider/cache/API layer is separate from the `obeos-earth/` React/Cesium client. The client must never promote stale, unavailable, or synthetic information into apparently live observations. Current CI covers Python tests, spatial contract export checks, client tests and client builds. Preserve those checks as the authoritative automated baseline.

## Optional task interface

Use a virtual environment. Requirements: Python 3.11+, Node.js 24 and pnpm 11.19.0 for parity with current CI. Optional `just` uses PowerShell on Windows.

| Command | Behavior |
| --- | --- |
| `just setup` | Install Python dev extras and frozen pnpm client lockfile. |
| `just api-check` | Existing Python tests and spatial-contract verification. |
| `just client-check` | Existing pnpm test/build steps. |
| `just check` | Both API and client automated checks. |
| `just serve` | Run local API on 127.0.0.1:8000; long-lived/manual. |
| `just client` | Run Cesium frontend locally; long-lived/manual. |
| `just release-check` | Run local checks; **does not release**. |

`just` is not used by current CI and is not needed for direct operation. Commands intentionally preserve the existing workflows rather than introducing a new dependency chain.

## Evidence required for any operational claim

Record commit SHA, OS/browser, UTC test time, input/source timestamp and fetched timestamp, provider/version, cache status, API status, screenshot/OBS clip where relevant, observed result and explicit pass/fail. See `docs/FRESHNESS.md`, `docs/BROADCAST-VALIDATION-2026-11-04.md`, and `docs/OBS-TEST-GUIDE.md`.

Acceptance scenarios should include: live provider; valid cache; stale cached feed; missing/corrupt cache; future-dated source and fetch timestamps; provider outage; API restart with missing persistence; preview-to-program isolation; and a real OBS output test when claiming broadcast readiness. Run only scenarios applicable to the changed subsystem and identify skipped ones.

Do not claim **NO ACTIVE ALERTS** on an unavailable feed. Do not show stale radar imagery as current. Synthetic model visualization is not observed data. CI success is not on-air acceptance.

## Failure and recovery

When a provider fails, show degraded/unavailable status and withhold unsafe visuals; retain only appropriately labeled last-known-good data. If a saved shot cannot be restored after startup, surface the warning and require an operator to retake/save. For deployment failure, revert to a tested revision and revalidate feed timestamps and program-source isolation. Never allow a test/local script to bypass production approval.

## Status and review

- **Built:** code and affected provider/client interfaces described.
- **Verified:** Python and client CI green at exact commit; list tests not run.
- **Released:** tested package/deploy artifact and rollback instructions available.
- **Operational:** actual live feeds, browser/OBS runtime, degraded-state and recovery evidence recorded in the target environment.

**AI assistance:** scope stated in PR.  
**Human verification:** only personally observed checks; mark unknown/not run honestly.
