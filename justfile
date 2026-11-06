set windows-shell := ["powershell.exe", "-NoProfile", "-Command"]

# Optional BES-1 aliases for the existing Python API + pnpm Cesium client.
default:
    @just --list

setup:
    python -m pip install -e ".[dev]"
    pnpm --dir obeos-earth install --frozen-lockfile

api-check:
    python -m pytest -q
    python tools/export_spatial_contracts.py --check

client-check:
    pnpm --dir obeos-earth test
    pnpm --dir obeos-earth build

check:
    just api-check
    just client-check

# API binds to loopback; manual runtime checks are tracked in ENGINEERING.md.
serve:
    earthglass serve --host 127.0.0.1 --port 8000

client:
    pnpm --dir obeos-earth dev

# Preflight only; no GitHub release or production deployment.
release-check:
    just check
