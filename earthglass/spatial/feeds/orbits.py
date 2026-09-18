"""Cached public orbital elements and bounded, local SGP4 projections."""

import json
import threading
from datetime import UTC, timedelta
from pathlib import Path

from ..models import utc_now
from ..network import ProviderError
from .base import Feed, ProviderSpec, timestamp
from .space import teme_to_wgs84

GROUPS = {
    "stations": "Space stations / ISS",
    "weather": "Weather satellites",
    "gps-ops": "GPS operational",
    "science": "Science",
    "starlink": "Starlink",
    "oneweb": "OneWeb",
}


class OrbitalFeed(Feed):
    source_url = "https://celestrak.org/NORAD/documentation/gp-data-formats.php"

    def __init__(self, http, credentials=lambda _: None, *, group="stations"):
        super().__init__(http, credentials)
        if group not in GROUPS:
            raise ValueError("Unsupported orbital group")
        self.group = group
        self.spec = ProviderSpec(
            "celestrak"
            if group == "stations"
            else "celestrak_" + group.replace("-", "_"),
            "satellites",
            GROUPS[group],
            15,
            "Local SGP4 predictions; elements refreshed at most every six hours; seven-day epoch limit; up to 5000 objects per group",
            "CelesTrak / Dr. T.S. Kelso",
            local=True,
            transport="polling",
        )
        self._lock = threading.RLock()
        self._records = []
        self._satellites = []
        self._retrieved = None
        self._retry = None
        self._error = None

    def configure_cache(self, directory):
        super().configure_cache(directory)
        self._path = Path(directory) / ("orbits-" + self.group + ".json")
        try:
            if self._path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Oversized orbital cache")
            value = json.loads(self._path.read_text(encoding="utf-8"))
            self._load(value["records"], timestamp(value["retrieved_at"]))
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _load(self, rows, retrieved):
        from sgp4 import omm
        from sgp4.api import Satrec

        if not isinstance(rows, list):
            raise ProviderError("invalid_elements", "Expected orbital element records")
        satellites = []
        accepted = []
        for row in rows[:5000]:
            try:
                sat = Satrec()
                from datetime import datetime

                row = dict(row)
                epoch = datetime.fromisoformat(str(row["EPOCH"]))
                if epoch.tzinfo is not None:
                    epoch = epoch.astimezone(UTC).replace(tzinfo=None)
                row["EPOCH"] = epoch.strftime("%Y-%m-%dT%H:%M:%S.%f")
                omm.initialize(sat, row)
                if not 0 < float(row["MEAN_MOTION"]) < 20:
                    raise ValueError("Invalid mean motion")
                satellites.append(
                    (str(row.get("OBJECT_NAME") or sat.satnum)[:120], sat)
                )
                accepted.append(row)
            except (ValueError, TypeError, KeyError, OverflowError):
                self.rejected += 1
        if not satellites:
            raise ProviderError("invalid_elements", "No valid OMM elements")
        with self._lock:
            self._satellites = satellites
            self._records = accepted
            self._retrieved = retrieved

    def fetch(self, viewport, now):
        if (
            not self.http.offline
            and (not self._retrieved or now - self._retrieved >= timedelta(hours=6))
            and (not self._retry or now >= self._retry)
        ):
            self._retry = now + timedelta(hours=6)
            try:
                rows = self.http.json(
                    "https://celestrak.org/NORAD/elements/gp.php",
                    params={"GROUP": self.group, "FORMAT": "json"},
                    cache_ttl=21600,
                )
                self._load(rows, now)
                self._error = None
                if hasattr(self, "_path"):
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self._path.with_suffix(".tmp")
                    tmp.write_text(
                        json.dumps(
                            {"retrieved_at": now.isoformat(), "records": self._records}
                        ),
                        encoding="utf-8",
                    )
                    tmp.replace(self._path)
            except ProviderError as exc:
                self._error = exc.code
                if not self._satellites:
                    raise
        if not self._satellites:
            raise ProviderError(
                "elements_unavailable",
                "No local orbital elements; enable online once to acquire this group",
            )
        values = self.project(now, viewport=viewport, interpolate=True)
        if not values:
            from sgp4.api import jday

            jd, fr = jday(
                now.year, now.month, now.day, now.hour, now.minute, now.second
            )
            if not any(
                abs(jd + fr - sat.jdsatepoch - sat.jdsatepochF) <= 7
                for _, sat in self._satellites
            ):
                raise ProviderError(
                    "stale_elements",
                    "Orbital elements exceed the seven-day prediction limit",
                )
        if self._error:
            self.rejected += 1
        return values

    def project(self, at, *, viewport=None, norad=None, limit=5000, interpolate=False):
        from sgp4.api import jday

        jd, fr = jday(
            at.year,
            at.month,
            at.day,
            at.hour,
            at.minute,
            at.second + at.microsecond / 1e6,
        )
        with self._lock:
            satellites = list(self._satellites)
            retrieved = self._retrieved
        values = []
        for name, sat in satellites:
            if norad is not None and sat.satnum != norad:
                continue
            epoch = sat.jdsatepoch + sat.jdsatepochF
            if abs(jd + fr - epoch) > 7:
                continue
            error, position, _ = sat.sgp4(jd, fr)
            if error:
                continue
            try:
                location = teme_to_wgs84(position, jd + fr)
                value = self.observation(
                    source_id=str(sat.satnum),
                    entity_id=f"norad:{sat.satnum}",
                    kind="predicted",
                    position=location,
                    observed_at=at,
                    received_at=utc_now(),
                    properties={
                        "name": name,
                        "norad_id": sat.satnum,
                        "group": self.group,
                        "propagator": "SGP4 / GMST",
                        "tle_epoch_jd": epoch,
                        "elements_retrieved_at": retrieved.isoformat(),
                        "elements_stale": (utc_now() - retrieved) > timedelta(hours=6),
                        "approximate_transform": "TEME to WGS84; polar motion omitted",
                    },
                )
                if viewport is not None and not viewport.contains(value.position):
                    continue
                if interpolate:
                    samples = []
                    for seconds in (0, 15, 30):
                        err, point, _ = sat.sgp4(jd, fr + seconds / 86400)
                        if not err:
                            samples.append(
                                {
                                    "time": (
                                        at + timedelta(seconds=seconds)
                                    ).isoformat(),
                                    **teme_to_wgs84(point, jd + fr + seconds / 86400),
                                }
                            )
                    value.properties["prediction_samples"] = samples
                values.append(value)
                if len(values) >= limit:
                    break
            except (ValueError, OverflowError):
                self.rejected += 1
        return values

    def status(self):
        with self._lock:
            return {
                "group": self.group,
                "label": GROUPS[self.group],
                "cached_objects": len(self._satellites),
                "elements_retrieved_at": self._retrieved.isoformat()
                if self._retrieved
                else None,
                "last_refresh_error": self._error,
                "prediction": "SGP4; seven-day epoch limit",
            }
