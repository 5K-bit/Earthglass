# EarthGlass

EarthGlass is the **renderer-agnostic geospatial layer engine** for the OBEOS ecosystem. It owns layer definitions, provider contracts, normalized feature payloads, metadata, and future caching/refresh behavior. It does **not** own the planetary renderer.

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

The current Leaflet page remains a lightweight development/demo surface. Leaflet is no longer part of the core layer model.

## Current milestone

Version 0.3 delivers the first live, reusable provider slice:

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

## Relationship to OBEOS Earth

**EarthGlass understands geospatial information. OBEOS Earth understands the planet.**

EarthGlass should remain usable without Cesium, React, or the OBEOS Earth frontend. OBEOS Earth can consume EarthGlass APIs and render returned layers on its 3D globe alongside weather, atmosphere, terrain, and time-dependent planetary systems.
