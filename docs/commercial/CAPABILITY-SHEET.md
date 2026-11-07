# EarthGlass Broadcast: Technical Capability Sheet
*OBEOS · v0.1.0 demo pre-release 1 (`broadcast-v0.1.0-demo.1`) · Draft for pilot conversations*

**What it is.** A real-time 3D globe weather graphics engine for TV and streaming stations. It renders a clean 16:9 program output that plays in OBS (Browser Source) or any browser, driven by a separate operator control room, using NOAA data with the source time shown on screen.

**Status in one line.** Demonstration-tested for supervised use. **Not certified for air:** the output is stamped PROTOTYPE / NOT FOR AIR.

## What works today
| Capability | Detail |
|---|---|
| Observed radar | NOAA CONUS base-reflectivity mosaic draped on the globe, with its observation time on screen. Each radar frame is stored once under its observation time and never rewritten, so a picture always matches its timestamp. If the frame is missing or older than 15 minutes, no radar is drawn and a red "RADAR OUT OF DATE · NO RADAR IS SHOWN" box appears instead. |
| Live NWS alerts | Active alerts only (Test/Exercise products rejected). Per-city banner with the most severe alert and its expiry; alert polygons coloured by severity. |
| Honest "all clear" | "No active NWS alerts" appears only when the alert feed is confirmed fresh (server retrieval, browser fetch and clock all checked, including future-dated timestamps). If the feed goes stale the banner reads "ALERT FEED UNAVAILABLE". |
| Model fields | Six NOAA GFS analysis products (temperature, wind, precipitation rate, cloud cover, pressure, humidity) with the model-cycle time on screen. The server refreshes them automatically when the cached cycle is old; a stale model is labelled "not for air". |
| Preview / Program | The operator stages a shot in preview and TAKES it to air. The server refuses a take if the staged shot changed. A direct cut that skips preview must be explicitly confirmed. |
| OBS-ready output | `broadcast.html?program=1` follows the server's on-air state from any machine. |
| Failure behaviour | If the backend stops, the program holds its last shot, the operator page shows CONTROL LINK LOST and TAKE is disabled. On restart the on-air shot is restored. If the on-air state cannot be saved, or a saved state was unreadable at startup, the operator page says so. |
| Control security | Write access needs a control token, or is limited to the local machine when none is set. |
| One-command deployment | `docker compose up --build` runs the API (radar, alerts, GFS, program control) and the web front on one origin, with data in a volume. Prototype only: no TLS or accounts. |

## Validation status
- **Tested in OBS Studio 32.0.4** (Browser Source, Windows 11, Intel UHD Graphics), 2026-11-04 to 2026-11-06. All six acceptance checks have recorded video evidence: globe renders; staging does not change the program; TAKE does; the program holds on backend loss with CONTROL LINK LOST and TAKE disabled; ALERT FEED UNAVAILABLE appears; control and the on-air shot recover after restart; a real GFS model-cycle timestamp is on screen. Tested commits and video timestamps are in `docs/BROADCAST-VALIDATION-2026-11-04.md`.
- Automated tests and CI pass on the tagged commit.
- **Not yet verified:** multi-hour or multi-day run (longest recorded run is 32 minutes), production or target GPU, 1080p/60 capture benchmark, review by a station meteorologist. All OBS evidence is from one machine and one operator.

## Data sources
NOAA / National Weather Service (alerts API, MRMS-derived radar mosaic via NCEP GeoServer, GFS model via NOMADS). US government public data; attribution shown on screen.

## Not done yet (be upfront with pilots)
- Not certified for air. A station-approved build removes the PROTOTYPE / NOT FOR AIR mark only after pilot sign-off.
- Radar covers the lower 48 states only. No Alaska, Hawaii or territories.
- Alerts issued by zone only (no polygon) appear in the banner but not as map shapes.
- No station branding system, graphics-engine (CasparCG/vMix/NDI) integration, user accounts, audit log or SLA.
- No hardened hosted deployment.

## Pilot scope (suggested)
Branding and colour system for one station, 4–6 market shots, severe-weather alert workflow, OBS/vMix operator training, a 4–6 week supervised pilot with a written reliability report. See the pilot offer draft.

## Licensing note
The core engine is open source (Apache-2.0). Commercial value is in the broadcast package: station identity, operator workflow, integration, support and a pilot-tested reliability process.
