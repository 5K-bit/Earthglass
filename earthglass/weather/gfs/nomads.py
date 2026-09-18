from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from earthglass.weather.gfs.cycles import as_utc
from earthglass.weather.storage.cache import weather_cancelled
from earthglass.weather.gfs.layers import GfsLayerSpec, get_layer_spec

NOMADS_GFS_FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
F000 = 0

LEVEL_QUERY_PARAMS: dict[str, tuple[str, ...]] = {
    "2 m above ground": ("lev_2_m_above_ground",),
    "10 m above ground": ("lev_10_m_above_ground",),
    "surface": ("lev_surface",),
    "mean sea level": ("lev_mean_sea_level",),
    "entire atmosphere": (
        "lev_entire_atmosphere",
        "lev_entire_atmosphere_\\(considered_as_a_single_layer\\)",
        "lev_entire_atmosphere_(considered_as_a_single_layer)",
    ),
    "entire atmosphere (considered as a single layer)": (
        "lev_entire_atmosphere_\\(considered_as_a_single_layer\\)",
        "lev_entire_atmosphere_(considered_as_a_single_layer)",
    ),
}


class GfsDownloadError(RuntimeError):
    pass


class GfsCycleUnavailable(GfsDownloadError):
    pass


class GfsNetworkError(GfsDownloadError):
    pass


@dataclass(frozen=True)
class GfsDownload:
    cycle: datetime
    url: str
    path: Path


def _query_items(cycle: datetime, spec: GfsLayerSpec, level_params: dict[str, str]) -> list[tuple[str, str]]:
    utc = as_utc(cycle)
    hour = utc.strftime("%H")
    items = [
        ("file", f"gfs.t{hour}z.pgrb2.0p25.f{F000:03d}"),
    ]

    for variable in sorted({field.variable for field in spec.fields}):
        items.append((f"var_{variable}", "on"))

    for level in sorted({field.level for field in spec.fields}):
        items.append((level_params[level], "on"))

    items.append(("dir", f"/gfs.{utc:%Y%m%d}/{hour}/atmos"))
    return items


def _level_param_variants(spec: GfsLayerSpec) -> list[dict[str, str]]:
    variants: list[dict[str, str]] = [{}]
    for level in sorted({field.level for field in spec.fields}):
        if level not in LEVEL_QUERY_PARAMS:
            raise KeyError(f"unsupported NOMADS level for {spec.id}: {level}")

        next_variants: list[dict[str, str]] = []
        for variant in variants:
            for param in LEVEL_QUERY_PARAMS[level]:
                candidate = dict(variant)
                candidate[level] = param
                next_variants.append(candidate)
        variants = next_variants

    return variants


def build_gfs_layer_urls(cycle: datetime, spec: GfsLayerSpec) -> list[str]:
    return [
        f"{NOMADS_GFS_FILTER_URL}?{urllib.parse.urlencode(_query_items(cycle, spec, level_params))}"
        for level_params in _level_param_variants(spec)
    ]


def build_gfs_layer_url(cycle: datetime, spec: GfsLayerSpec) -> str:
    return build_gfs_layer_urls(cycle, spec)[0]


def build_gfs_temperature_url(cycle: datetime) -> str:
    return build_gfs_layer_url(cycle, get_layer_spec("temperature"))


def _looks_like_grib(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) == b"GRIB"


def download_gfs_layer(spec: GfsLayerSpec, cycle: datetime, destination: Path) -> GfsDownload:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    cycle_messages: list[str] = []

    for url in build_gfs_layer_urls(cycle, spec):
        if weather_cancelled.get()():
            raise GfsNetworkError("Weather refresh cancelled")
        partial.unlink(missing_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "OBEOS-Earth/0.2"})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                with partial.open("wb") as handle:
                    size = 0
                    deadline = time.monotonic() + 60
                    while True:
                        if weather_cancelled.get()() or time.monotonic() > deadline:
                            raise GfsNetworkError("Weather download cancelled or deadline exceeded")
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > 64 * 1024 * 1024:
                            raise GfsNetworkError("Weather response exceeds 64 MiB")
                        handle.write(chunk)
        except urllib.error.HTTPError as exc:
            if exc.code in {400, 403, 404, 503}:
                cycle_messages.append(f"HTTP {exc.code} for {cycle.isoformat()}")
                continue
            raise GfsNetworkError(f"NOMADS returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise GfsNetworkError(f"Could not reach NOMADS: {exc.reason}") from exc

        if _looks_like_grib(partial):
            partial.replace(destination)
            return GfsDownload(cycle=as_utc(cycle), url=url, path=destination)

        body = partial.read_text(encoding="utf-8", errors="ignore")[:500]
        partial.unlink(missing_ok=True)
        lowered = body.lower()
        if "not present" in lowered or "not available" in lowered or "does not exist" in lowered:
            cycle_messages.append(f"GFS cycle is not available: {cycle.isoformat()}")
        else:
            cycle_messages.append(f"NOMADS did not return GRIB2 data for {cycle.isoformat()}")

    raise GfsCycleUnavailable("; ".join(cycle_messages) or f"No GRIB2 data for {cycle.isoformat()}")


def download_gfs_temperature(cycle: datetime, destination: Path) -> GfsDownload:
    return download_gfs_layer(get_layer_spec("temperature"), cycle, destination)


def resolve_and_download_layer(spec: GfsLayerSpec, candidates: list[datetime], raw_dir: Path) -> GfsDownload:
    cycle_errors: list[str] = []
    layer_raw_dir = raw_dir / spec.id

    for cycle in candidates:
        utc = as_utc(cycle)
        destination = layer_raw_dir / f"{utc:%Y%m%d_%H}_f{F000:03d}.grib2"
        try:
            if destination.exists() and _looks_like_grib(destination):
                return GfsDownload(
                    cycle=utc,
                    url=build_gfs_layer_url(utc, spec),
                    path=destination,
                )
            return download_gfs_layer(spec, utc, destination)
        except GfsCycleUnavailable as exc:
            cycle_errors.append(str(exc))
            continue

    raise GfsCycleUnavailable("; ".join(cycle_errors) or "No GFS candidates were available")


def resolve_and_download(candidates: list[datetime], raw_dir: Path) -> GfsDownload:
    return resolve_and_download_layer(get_layer_spec("temperature"), candidates, raw_dir)
