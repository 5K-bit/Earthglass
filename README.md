<div align="center">

<img src="assets/brand/github-banner.svg" alt="EarthGlass — Geospatial information, independent of the renderer. A Blackfong project." width="1200">

**Geospatial information, independent of the renderer.**

![Stage](https://img.shields.io/badge/stage-Provider%20and%20globe%20integration-83bfa9?style=for-the-badge&labelColor=0c1220)
[![CI](https://img.shields.io/github/actions/workflow/status/5K-bit/Earthglass/obeos-component-ci.yml?branch=main&style=for-the-badge&label=CI&labelColor=0c1220&color=83bfa9)](https://github.com/5K-bit/Earthglass/actions/workflows/obeos-component-ci.yml)

[Installation](#installation) · [API](#api) · [CLI](#cli) · [Local system](#run-the-complete-local-system)

</div>

---

# EarthGlass

| Ingest | Preserve | Present |
|---|---|---|
| Provider contracts and normalized GeoJSON | Provenance, cache and freshness metadata | HTTP API, CLI and OBEOS Earth client |

EarthGlass is the **renderer-agnostic geospatial layer engine** for the OBEOS ecosystem. It owns layer definitions, provider contracts, normalized feature payloads, metadata, and caching/refresh behavior. It does **not** own the planetary renderer.

OBEOS Earth is the intended 3D planetary runtime and Cesium client. EarthGlass supplies reusable geospatial information that OBEOS Earth, a CLI, a 2D map, or another client can consume without importing renderer-specific code.

## Architecture

```text
Geospatial providers
  USGS / future feeds
        |
        v
EarthGlass provider adapters
        |
        v
LayerRegistry + LayerDefinition
        |
        +--> FastAPI JSON API
        +--> Typer CLI
        +--> Leaflet demo surface
        +--> OBEOS Earth / Cesium client
```

The repository now contains two deliberately separated packages:

- `earthglass/` — Python ingestion, validation, cache, lifecycle, CLI, and HTTP API
- `obeos-earth/` — React/TypeScript/Cesium planetary client consuming that API

The legacy Leaflet page remains a lightweight development surface. Leaflet and Cesium are not part of the EarthGlass core model.

## Current milestone

Version 0.4 connects the first provider slice to the planetary client:

- renderer-independent `LayerDefinition`
- central `LayerRegistry`
- provider manager and observable lifecycle state
- live USGS all-day earthquake retrieval
- validated, normalized GeoJSON features
- collection- and feature-level source provenance
- atomic persistent cache with explicit fresh/stale metadata
- degraded operation from the last valid cache
- FastAPI and CLI consuming the same core registry
- feature, refresh, and provider-status API endpoints
- tests enforcing that serialized layer definitions do not depend on Leaflet or Cesium
- separate Cesium globe with bundled Natural Earth imagery and no Ion token requirement
- magnitude-scaled earthquake markers, event details, camera flight, attribution, and status
- five-minute background refresh plus explicit refresh controls
- CORS restricted to the local OBEOS Earth development/preview origins by default

## Layout

```text
earthglass/
  earthglass/
    __init__.py
    layers.py          # layer model + registry
    providers.py       # validated contracts + provider manager
    cache.py           # persistent normalized-feature cache
    usgs.py            # live earthquake adapter
    runtime.py         # default provider composition
    cli.py             # Typer adapter
    web/
      app.py           # FastAPI adapter + demo UI
      templates/
      static/
  tests/
    test_layers.py
    test_web.py
    test_cli.py
  pyproject.toml
  obeos-earth/
    src/api.ts        # typed EarthGlass HTTP client
    src/App.tsx       # Cesium world presentation
    src/api.test.ts   # client contract tests
    vite.config.ts    # Cesium runtime assets
  README.md
```

## Installation

```bash
python -m pip install -e ".[dev]"
```

## API

- `GET /health`
- `GET /api/status`
- `GET /api/layers`
- `GET /api/layers/{layer_id}`
- `GET /api/layers/{layer_id}/features`
- `POST /api/layers/{layer_id}/refresh`
- `GET /api/providers/status`
- `GET /` — optional Leaflet demo surface

Run locally:

```bash
earthglass serve
earthglass serve --reload
```

## CLI

```bash
earthglass --help
earthglass layers
earthglass cache status
earthglass refresh earthquakes
```

By default, provider data is cached under `.earthglass-cache/`. Set
`EARTHGLASS_CACHE_DIR` to choose another location. When USGS cannot be reached,
EarthGlass returns the last validated cache with `metadata.cache.stale: true` and
reports the provider as `degraded`. Without a valid cache, the feature API returns
HTTP 503; stale external data is never represented as live.

## Development

```bash
pytest
```

## Run the complete local system

Requirements: Python 3.11+, Node.js 22+, and pnpm.

Install once:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
pnpm --dir obeos-earth install
```

Start the EarthGlass API in the first terminal:

```powershell
.\.venv\Scripts\earthglass.exe serve --host 127.0.0.1 --port 8000
```

Start OBEOS Earth in the second terminal:

```powershell
pnpm --dir obeos-earth dev
```

Open `http://127.0.0.1:5173/`. The client reads
`http://127.0.0.1:8000/api/layers/earthquakes/features` by default. Override
the API before building or starting the client when needed:

```powershell
$env:VITE_EARTHGLASS_API_BASE="https://earthglass.example/api"
```

Frontend verification:

```powershell
pnpm --dir obeos-earth test
pnpm --dir obeos-earth build
```

## Relationship to OBEOS Earth

**EarthGlass understands geospatial information. OBEOS Earth understands the planet.**

EarthGlass remains usable without Cesium, React, or the OBEOS Earth frontend. OBEOS Earth consumes only the public EarthGlass API and translates normalized observations into Cesium entities. Cesium imports and renderer state remain confined to `obeos-earth/`.
