from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

from ..network import ProviderError
from .base import Feed, ProviderSpec, number, timestamp


def teme_to_wgs84(position_km, julian_day):
    # TEME -> Earth fixed using GMST. Polar motion is not modeled.
    centuries = (julian_day - 2451545.0) / 36525.0
    gmst = math.radians(
        (
            280.46061837
            + 360.98564736629 * (julian_day - 2451545.0)
            + 0.000387933 * centuries**2
            - centuries**3 / 38710000
        )
        % 360
    )
    x = position_km[0] * math.cos(gmst) + position_km[1] * math.sin(gmst)
    y = -position_km[0] * math.sin(gmst) + position_km[1] * math.cos(gmst)
    z = position_km[2]
    radial = math.hypot(x, y)
    eccentricity2 = 6.69437999014e-3
    latitude = math.atan2(z, radial * (1 - eccentricity2))
    for _ in range(8):
        normal = 6378.137 / math.sqrt(1 - eccentricity2 * math.sin(latitude) ** 2)
        latitude = math.atan2(z + eccentricity2 * normal * math.sin(latitude), radial)
    normal = 6378.137 / math.sqrt(1 - eccentricity2 * math.sin(latitude) ** 2)
    altitude = (
        radial / max(math.cos(latitude), 1e-12) - normal
        if radial > 1e-8
        else abs(z) - 6356.752314245
    )
    return {
        "latitude": math.degrees(latitude),
        "longitude": math.degrees(math.atan2(y, x)),
        "altitude_m": altitude * 1000,
        "altitude_reference": "ellipsoid",
    }


class SatelliteFeed(Feed):
    spec = ProviderSpec(
        "celestrak",
        "satellites",
        "Satellites",
        10,
        "SGP4 predictions from CelesTrak active TLEs; first 5000 records; polar motion omitted",
        "CelesTrak / Dr. T.S. Kelso",
        transport="polling",
        max_records=5000,
    )
    source_url = "https://celestrak.org/"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._satellites = []
        self._retrieved = None
        self._next_elements_retry = None
        self._elements_stale = False
        self.cache_directory = None

    def fetch(self, viewport, now):
        try:
            from sgp4.api import Satrec, jday
        except ImportError as exc:
            raise ProviderError(
                "dependency_missing", "Install EarthGlass's sgp4 dependency"
            ) from exc
        cache_path = Path(self.cache_directory) / "celestrak-elements.json" if self.cache_directory else None
        text = None
        retrieved = now
        if self._retrieved is None and cache_path:
            try:
                with cache_path.open("rb") as stream:
                    raw = stream.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError("Orbital cache is too large")
                cached = json.loads(raw)
                cached_at = timestamp(cached["retrieved"])
                if timedelta(0) <= now - cached_at < timedelta(hours=6):
                    text, retrieved = cached["text"], cached_at
            except (OSError, ValueError, KeyError, TypeError):
                pass
        due = self._retrieved is None or now - self._retrieved > timedelta(hours=6)
        if due and text is None and (self._next_elements_retry is None or now >= self._next_elements_retry):
            try:
                text = self.http.text(
                    "https://celestrak.org/NORAD/elements/gp.php",
                    params={"GROUP": "active", "FORMAT": "tle"},
                )
                self._elements_stale = False
            except ProviderError:
                if not self._satellites or now - self._retrieved > timedelta(days=7):
                    raise
                self._elements_stale = True
                self._next_elements_retry = now + timedelta(hours=1)
        if text is not None:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            satellites = []
            for index in range(len(lines) - 1):
                if lines[index].startswith("1 ") and lines[index + 1].startswith("2 "):
                    name = (
                        lines[index - 1].removeprefix("0 ")
                        if index > 0
                        else "Satellite"
                    )
                    try:
                        sat = Satrec.twoline2rv(lines[index], lines[index + 1])
                        satellites.append((name, sat))
                    except ValueError:
                        continue
            if not satellites:
                raise ProviderError(
                    "invalid_tle", "No valid orbital elements were returned"
                )
            self._satellites = satellites[: self.spec.max_records]
            self._retrieved = retrieved
            self._next_elements_retry = None
            if cache_path and retrieved == now:
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache_path.with_suffix(".tmp")
                    temporary.write_text(json.dumps({"retrieved": now.isoformat(), "text": text}), encoding="utf-8")
                    temporary.replace(cache_path)
                except OSError:
                    pass  # Disk-cache failure must not discard validated live orbital elements.
        if self._retrieved and now - self._retrieved > timedelta(days=7):
            raise ProviderError("stale_elements", "Orbital elements exceeded the seven-day prediction limit")
        jd, fraction = jday(
            now.year,
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second + now.microsecond / 1e6,
        )
        records = []
        for name, satellite in self._satellites:
            error, position, velocity = satellite.sgp4(jd, fraction)
            if error:
                continue
            try:
                observation = self.observation(
                    source_id=str(satellite.satnum),
                    entity_id=f"norad:{satellite.satnum}",
                    kind="predicted",
                    position=teme_to_wgs84(position, jd + fraction),
                    observed_at=now,
                    received_at=now,
                    properties={
                        "name": name,
                        "norad_id": satellite.satnum,
                        "propagator": "SGP4 / GMST",
                        "tle_epoch_jd": satellite.jdsatepoch + satellite.jdsatepochF,
                        "elements_retrieved_at": self._retrieved.isoformat(),
                        "elements_stale": self._elements_stale,
                        "approximate_transform": "TEME to WGS84; polar motion omitted",
                    },
                )
                if viewport.contains(observation.position):
                    records.append(observation)
            except ValueError:
                self.rejected += 1
        return records


class LaunchFeed(Feed):
    spec = ProviderSpec(
        "launch_library",
        "launches",
        "Space launches",
        900,
        "Launch Library upcoming launch sites and scheduled metadata; no live ascent telemetry",
        "Launch Library 2 — The Space Devs",
        max_records=100,
    )
    source_url = "https://thespacedevs.com/"

    def fetch(self, viewport, now):
        data = self.http.json(
            "https://ll.thespacedevs.com/2.3.0/launches/upcoming/",
            params={"limit": 100, "mode": "detailed"},
            cache_ttl=self.spec.interval_seconds,
        )

        def parse(row):
            pad = row.get("pad") or {}
            location = pad.get("location") or {}
            lat = number(pad.get("latitude"), number(location.get("latitude")))
            lon = number(pad.get("longitude"), number(location.get("longitude")))
            if lat is None or lon is None:
                return None
            return self.observation(
                source_id=str(row["id"]),
                position={"latitude": lat, "longitude": lon},
                observed_at=timestamp(row.get("last_updated"), fallback=now),
                received_at=now,
                kind="catalog",
                properties={
                    "name": row.get("name"),
                    "scheduled_at": row.get("net"),
                    "status": (row.get("status") or {}).get("name"),
                    "pad": pad.get("name"),
                    "description": str(
                        (row.get("mission") or {}).get("description") or ""
                    )[:2000],
                },
            )

        return self.normalize(data.get("results"), parse)
