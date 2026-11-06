## Problem, scope and boundaries
- Changed providers, data contracts, API endpoints or Cesium views:
- Observed failure / expected behavior:
- Live vs cache vs model vs synthetic data implications:

## Automated verification (exact commit and evidence)
- [ ] `python -m pytest -q`
- [ ] `python tools/export_spatial_contracts.py --check`
- [ ] `pnpm --dir obeos-earth test`
- [ ] `pnpm --dir obeos-earth build`
- CI SHA and run:
- Missing optional dependencies / skipped tests:

## Failure states, security and recovery
- [ ] Stale/unavailable states cannot appear live
- [ ] Relevant time-skew, failed-fetch, corrupt-cache and restart scenarios considered
- [ ] Operator-approved state changes do not leak to program preview
- Rollback / degrade behavior:
- Out-of-scope and still unverified:

## Manual environment acceptance
- Browser/OS, live feed source/time, operator steps and evidence:
- [ ] Actual live browser/OBS check performed, **if claimed**
- [ ] Failure/recovery observed, **if claimed**
- [ ] No on-air-ready claim solely from CI

## BES-1 lifecycle
- [ ] Built
- [ ] Verified
- [ ] Released
- [ ] Operational

AI assistance:  
Human verification:
