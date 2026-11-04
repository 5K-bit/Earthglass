# EarthGlass Broadcast — prototype v0.1

An isolated **16:9 weather presentation preview** built on the existing OBEOS Earth / Cesium dependencies. It does not change the primary EarthGlass geospatial API or existing OBEOS Earth screen.

## Run

From this repository root (Node 22+ and pnpm 11.19):

```powershell
pnpm --dir obeos-earth install --frozen-lockfile
pnpm --dir obeos-earth dev
```

Open **http://127.0.0.1:5173/broadcast.html** for the control room or **http://127.0.0.1:5173/broadcast.html?program=1** for a presentation-only browser capture. The page has four camera shots and six weather-product choices. Cesium's bundled Natural Earth imagery renders the globe without an Ion token.

To use a running EarthGlass/OBEOS Earth **weather-enabled host**:

```powershell
$env:VITE_BROADCAST_API_ORIGIN="http://127.0.0.1:8000"
pnpm --dir obeos-earth dev
```

The origin must serve both `GET /api/weather/layers` and `GET /weather/gfs/latest/<filename>` from the **same host**. The basic `earthglass serve` app does **not** mount the weather API by itself: this feature is implemented in `earthglass/weather/api.py` for the canonical Earth host. Configure CORS there if using a separate origin.

## Data integrity

- Without a connected weather host or available local layer, the globe uses explicitly **synthetic**, illustrative overlays.
- Real weather products are the six existing NOAA GFS **forecast-hour-zero model analysis** layers. They are **not live radar**, observed current conditions, or forecast animations.
- A model-analysis provenance flag, f000 forecast hour, allowed local image path and trustworthy UTC timestamps are required before the renderer accepts a source as a model layer.
- Model cycles older than 10 hours, with anomalous future timestamps, or with unsupported provenance are flagged. No scene is certified for live on-air use.
- Every view is permanently marked **PROTOTYPE / NOT FOR AIR** at this stage, including the clean program preview. This is intentional until a meteorologist approves content rules and the engineering team verifies output reliability.

## Build/test

```powershell
pnpm --dir obeos-earth test
pnpm --dir obeos-earth build
```

The build now includes `dist/broadcast.html` alongside the existing `dist/index.html` and `dist/presence.html`.

To deploy the static preview, publish the `obeos-earth/dist` directory (e.g. Netlify). The static deployment is useful for pitching the visual concept and automatically enters clearly marked synthetic mode if no live API is accessible. **No paid NOAA source, commercial map tile, or broadcast hardware is required for the preview.**

## Why this is not an on-air product yet

Before selling production use, validate: forecast/observation differentiation; NWS severe-weather watches/warnings and radar ingest; precise valid-time display, local and UTC timezone controls; fallback on data/network failures; 1920×1080/4K sustained output; animation and cue/rundown controls; rendering at station hardware; NDI/SDI/key/fill or supported capture bridge; alert sign-off by station meteorologists; logs/uptime, retry behavior, accessibility, and licensing for each data and imagery source.

Recommended first commercial pitch: **local weather storytelling studio for streaming/social digital output**, not a replacement for the newsroom's mission-critical severe-weather broadcast chain.
