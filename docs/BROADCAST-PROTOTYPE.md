# EarthGlass Broadcast — prototype v0.1

**Status: demonstration candidate. Browser-level integration verified; OBS acceptance: operator reports all six checks passed; video evidence is partial. Not certified for air.**

EarthGlass Broadcast is a browser-rendered, 16:9 Cesium weather storytelling prototype with a separate operator/control view and program output. It is built on the existing OBEOS Earth frontend and the EarthGlass FastAPI layer. Every presentation carries **PROTOTYPE / NOT FOR AIR**.

See [OBS and release validation record](BROADCAST-VALIDATION-2026-11-04.md) for test evidence, scope and remaining release limits.

## Start the demonstration

From the repository root, with Node 22+ and pnpm 11.19:

```powershell
pnpm --dir obeos-earth install --frozen-lockfile
$env:VITE_BROADCAST_API_ORIGIN="http://127.0.0.1:8000"
pnpm --dir obeos-earth dev
```

Start the EarthGlass API separately on `127.0.0.1:8000` before using live radar, alerts or program control. The EarthGlass FastAPI app exposes the radar, alert and program endpoints. **It does not automatically mount the GFS weather catalog**; the six GFS analysis products require the separately configured, weather-enabled canonical Earth host and image endpoints. Set `VITE_BROADCAST_API_ORIGIN` to the origin serving the needed endpoints. If frontend and backend run on different origins, configure allowed CORS origins.

- Operator interface: `http://127.0.0.1:5173/broadcast.html`
- Program/OBS Browser Source: `http://127.0.0.1:5173/broadcast.html?program=1`
- Direct shot: `http://127.0.0.1:5173/broadcast.html?scene=mia&field=radar`

Four programmed locations are New York, Miami, Chicago and San Francisco. The product selector includes one observed radar product and six NOAA GFS forecast-hour-zero model-analysis fields. Cesium's bundled Natural Earth imagery renders the base globe without an Ion token.

## Preview, TAKE and program output

Selecting a shot or field stages **preview** through `POST /api/broadcast/preview`. Only an explicit TAKE calls `POST /api/broadcast/take` and changes the on-air state. The backend refuses a TAKE when its scene/product no longer matches the staged preview (HTTP 409). The program output polls `GET /api/broadcast/program` from its own browser context; it **does not use BroadcastChannel** and can therefore be captured separately in OBS Browser Source. The last program state is persisted across process restarts. Loss of the control link disables TAKE in the operator UI; the program holds the previously selected shot while reconnection is attempted.

Backend program writes require `X-Control-Token` when `EARTHGLASS_CONTROL_TOKEN` is configured, otherwise writes are restricted to loopback clients. Keep the prototype behind a trusted network boundary. Token auth is not a replacement for station-grade access control, auditing, TLS and production security review.

## Weather-data truth and failure behavior

- **Observed radar:** NOAA/NCEP CONUS base-reflectivity mosaic, placed on a geographic rectangle with its **observation** time (not download time). If the metadata, observation age, or connection fails validation, the image is withheld and any prior radar overlay is removed. The program output shows a large **RADAR OUT OF DATE** (or **RADAR UNAVAILABLE**) warning, keeps the last observation time in a **RADAR STALE · NO DATA SHOWN** label, and replaces the bottom line with **NO CURRENT RADAR**. The freshness threshold is 15 minutes, with additional server/client freshness rules. No simulated radar is substituted.
- **NWS alerts:** Only actual (non-test/non-exercise), unexpired alerts are considered. Location-specific alert banners include zone-only alerts; only alerts with polygon geometries appear as globe shapes. The browser requires the backend cache flag to be explicitly non-stale, an NWS retrieval age of at most **5 minutes**, and its own last successful fetch within **3 minutes**. Missing freshness metadata is treated as unavailable. An unavailable/stale alert feed does not display **NO ACTIVE NWS ALERTS** or stale alert polygons.
- **NOAA GFS:** Temperature, 10 m wind, precipitation rate, cloud cover, pressure and humidity are *forecast-hour-zero model analyses*; they are not observed radar or current station measurements. UTC model-cycle time and stale status are shown. Catalogs and assets require compatible provenance, timestamp and local-path checks.
- **Offline demonstration:** When real GFS model layers are unavailable, synthetic **illustrative** weather graphics may appear and are prominently labeled as not real data. The radar product never fabricates an observed radar frame.

## OBS capture acceptance

In OBS Studio, create a Browser Source pointing to `/broadcast.html?program=1`, with canvas source dimensions **1920 × 1080** and an initial **30 FPS** capture setting (a setting, not a measured render guarantee). Open the operator view separately.

**Real OBS acceptance has been run (2026-11-04/05) with the operator reporting all six checks passed.** The six checks are defined in the [OBS test guide](OBS-TEST-GUIDE.md); Recorded video evidence is complete only for the first check; the rest rest on the operator's report, and the long alert-feed-unavailable state and a GFS timestamp have not been captured. See the [validation record](BROADCAST-VALIDATION-2026-11-04.md).

## Build and verification

```powershell
pnpm --dir obeos-earth test
pnpm --dir obeos-earth build
python -m pytest -q
```

The Vite build includes `dist/broadcast.html`, `dist/index.html` and `dist/presence.html`. A static host can preview the visual concept, but it cannot supply the station's live weather API or server-held program control without a separately hosted backend.

## Known limitations / pilot boundaries

This is a supervised engineering and sales prototype, **not a station-approved weather-alert chain or certified on-air graphics system**. Radar covers CONUS only. Zone-only alerts have no geographic shape until a zone geometry resolver is added. The code has not been independently benchmarked for sustained 1080p/60 or 4K output on a production GPU, multi-day unattended operation, rundown integration, NDI/SDI/key-fill delivery, failover, per-user permissions, audit logs or an SLA. Station meteorologists must approve content, alert handling and use of source data before any operational deployment.

Commercial pilot recommendation: run as an optional digital/streaming weather storytelling system alongside existing broadcast graphics, with station branding, local shots and a written reliability report. The core EarthGlass engine is Apache-2.0; licensing/service terms for station customization, deployment, integration, training and support are separate.
