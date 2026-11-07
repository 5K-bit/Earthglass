# EarthGlass Broadcast: Paid Pilot Offer (DRAFT)
*OBEOS · prepared for discussion · not a contract*

## What the station gets
A supervised 4–6 week evaluation of EarthGlass Broadcast, a real-time 3D globe weather graphics engine that runs as an OBS or browser source and is driven by a separate operator control room using NOAA / National Weather Service data.

## Included
1. Setup on station hardware or a hosted instance (a one-command container deployment exists), with the station's OBS or switcher chain.
2. One station look: colours, logo, lower-third style.
3. 4–6 market shots chosen with the weather team.
4. Severe-weather workflow: live NWS alerts with expiry, and a visible "feed unavailable" state instead of a false "all clear".
5. Radar and model products with their source times always on screen; stale radar is withheld rather than shown.
6. Operator training (about 2 hours) and a one-page operator card.
7. A written reliability report at the end: uptime, outages, data-freshness events.

## What it is not (stated up front)
- **Not certified for air.** The output carries a PROTOTYPE / NOT FOR AIR mark during the pilot. Removing it is a decision made together after the pilot.
- Supervised use only. Not for unattended broadcast or as the sole source for emergency-alert decisions.
- Lower-48 radar only. No Alaska, Hawaii or territories yet.
- No uptime guarantee (SLA) during the pilot.

## Evidence available today
- Automated tests and CI passing on the tagged pre-release (`broadcast-v0.1.0-demo.1`).
- A real OBS Studio 32.0.4 Browser Source test with video evidence for all six acceptance checks: preview/TAKE separation, hold and CONTROL LINK LOST on backend loss, ALERT FEED UNAVAILABLE, recovery after restart, and a real GFS model-cycle timestamp. Record: `docs/BROADCAST-VALIDATION-2026-11-04.md`.
- Known gaps are listed in the capability sheet. Evidence so far is from one machine and one operator, with no multi-day run yet. Running a long soak test and having a station meteorologist review the alert wording are the first things to do together.

## Success criteria (to agree with the station)
- The weather team can stage and take at least 6 shots without assistance after training.
- No unreported stale data on screen during the pilot.
- The station decides at the end: continue to a license, extend the pilot, or stop.

## Commercial terms (placeholders to fill in; not researched)
- Pilot fee: [to be set by OBEOS]
- Optional follow-on license and identity package: [to be set]
- The core engine stays open source (Apache-2.0); the fee covers integration, branding, training and support.
