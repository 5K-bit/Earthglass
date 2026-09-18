"""Official hazard and aviation products, normalized without renderer dependencies."""

import hashlib
import json
import re
from pathlib import Path

from ..geometry import normalize_geometry, observation_in_view
from ..network import ProviderError
from .base import Feed, ProviderSpec, timestamp


class EonetFeed(Feed):
    spec = ProviderSpec(
        "nasa_eonet",
        "natural_events",
        "NASA natural events",
        900,
        "NASA curated open events in the selected area; event times may be date-only",
        "NASA Earth Observatory Natural Event Tracker",
    )
    source_url = "https://eonet.gsfc.nasa.gov/"

    def fetch(self, viewport, now):
        self.bounded(viewport, 360)
        data = self.http.json(
            "https://eonet.gsfc.nasa.gov/api/v3/events",
            cache_ttl=900,
            params={
                "status": "open",
                "days": 30,
                "limit": 500,
                "bbox": f"{viewport.west},{viewport.north},{viewport.east},{viewport.south}",
            },
        )

        def parse(row):
            geometries = row.get("geometry") or []
            if not geometries:
                return None
            record = max(geometries, key=lambda g: timestamp(g["date"]))
            geometry, position, bounds = normalize_geometry(record)
            value = self.observation(
                source_id=row["id"],
                entity_type="natural_event",
                position=position,
                observed_at=timestamp(record["date"]),
                received_at=now,
                properties={
                    "name": row["title"],
                    "description": str(row.get("description") or "")[:5000],
                    "categories": row.get("categories", [])[:20],
                    "sources": row.get("sources", [])[:20],
                    "closed": row.get("closed"),
                    "geometry": geometry,
                    "spatial_bounds": bounds,
                    "magnitude_value": record.get("magnitudeValue"),
                    "magnitude_unit": record.get("magnitudeUnit"),
                },
                source_url=row.get("link") or self.source_url,
            )
            return value if observation_in_view(value, viewport) else None

        return self.normalize(data.get("events"), parse)


class NWSAlertFeed(Feed):
    spec = ProviderSpec(
        "noaa_nws",
        "weather_alerts",
        "NWS weather alerts",
        120,
        "US NWS alerts; geographic polygons or official affected-zone geometry",
        "NOAA / National Weather Service",
        max_records=1000,
    )
    source_url = "https://www.weather.gov/"

    def configure_cache(self, directory):
        super().configure_cache(directory)
        self._zones = {}
        self._zone_cursor = 0
        self._zone_path = Path(directory) / "nws-zones.json"
        try:
            if self._zone_path.stat().st_size < 8 * 1024 * 1024:
                self._zones = json.loads(self._zone_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def fetch(self, viewport, now):
        if not hasattr(self, "_zones"):
            self._zones = {}
            self._zone_cursor = 0
        data = self.http.json(
            "https://api.weather.gov/alerts",
            params={"active": "true"},
            cache_ttl=120,
            headers={"Accept": "application/geo+json"},
        )
        missing = list(
            dict.fromkeys(
                url
                for row in data.get("features", [])
                if not row.get("geometry")
                for url in (row.get("properties", {}).get("affectedZones") or [])
                if url not in self._zones
                and re.fullmatch(
                    r"https://api.weather.gov/zones/(county|forecast|fire)/[A-Z]{3}[0-9]{3}",
                    url,
                )
            )
        )
        # Two bounded zone lookups per refresh; partial coverage is reported until cached.
        for offset in range(min(2, len(missing))):
            url = missing[(self._zone_cursor + offset) % len(missing)]
            try:
                zone = self.http.json(url, cache_ttl=86400)
                geometry, _, _ = normalize_geometry(zone.get("geometry"), max_points=80)
                self._zones[url] = geometry
            except (ProviderError, ValueError, TypeError):
                pass
        self._zone_cursor += 2
        if len(self._zones) > 512:
            self._zones = dict(list(self._zones.items())[-512:])
        if hasattr(self, "_zone_path"):
            self._zone_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._zone_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._zones), encoding="utf-8")
            tmp.replace(self._zone_path)

        def parse(row):
            props = row["properties"]
            if props.get("status") not in {None, "Actual"}:
                return None
            expires = timestamp(props["expires"]) if props.get("expires") else None
            if expires and expires < now:
                return None
            raw = row.get("geometry")
            zone_derived = False
            zone_missing = 0
            if not raw:
                polygons = []
                for url in props.get("affectedZones") or []:
                    zone = self._zones.get(url)
                    if not zone:
                        zone_missing += 1
                        continue
                    polygons.extend(
                        [zone["coordinates"]]
                        if zone["type"] == "Polygon"
                        else zone["coordinates"]
                        if zone["type"] == "MultiPolygon"
                        else []
                    )
                if not polygons:
                    self.rejected += 1
                    return None
                raw = {"type": "MultiPolygon", "coordinates": polygons[:8]}
                zone_derived = True
                if zone_missing or len(polygons) > 8:
                    self.rejected += 1
            geometry, position, bounds = normalize_geometry(raw, max_points=150)
            value = self.observation(
                source_id=hashlib.sha256(str(row["id"]).encode()).hexdigest()[:32],
                entity_type="weather_alert",
                position=position,
                observed_at=timestamp(props.get("sent") or props["effective"]),
                received_at=now,
                properties={
                    **{
                        k: props.get(k)
                        for k in (
                            "event",
                            "severity",
                            "certainty",
                            "urgency",
                            "effective",
                            "onset",
                            "expires",
                            "ends",
                            "areaDesc",
                            "headline",
                            "senderName",
                        )
                    },
                    "name": props.get("event"),
                    "description": str(props.get("description") or "")[:10000],
                    "instructions": str(props.get("instruction") or "")[:6000],
                    "alert_id": row["id"],
                    "zone_derived": zone_derived,
                    "unmapped_zones": zone_missing,
                    "geometry": geometry,
                    "spatial_bounds": bounds,
                },
                source_url=row["id"]
                if str(row["id"]).startswith("https://")
                else self.source_url,
            )
            return value if observation_in_view(value, viewport) else None

        values = self.normalize(data.get("features"), parse)
        self.status_message = f"{len(values)} alerts in view; {self.rejected} records/zones unavailable; {len(self._zones)} zone geometries cached"
        return values


class AviationWeatherFeed(Feed):
    source_url = "https://aviationweather.gov/"

    def __init__(self, http, credentials=lambda _: None, *, product="metar"):
        super().__init__(http, credentials)
        self.product = product
        self.spec = ProviderSpec(
            "noaa_awc_" + product,
            "aviation_" + product,
            product.upper(),
            300,
            "NOAA AWC regional aviation weather; no navigation or dispatch assurance",
            "NOAA Aviation Weather Center",
            max_records=400,
        )

    def fetch(self, viewport, now):
        endpoint = {
            "metar": "metar",
            "taf": "taf",
            "sigmet": "isigmet",
            "pirep": "pirep",
            "gairmet": "gairmet",
        }[self.product]
        params = {"format": "geojson"}
        if self.product in {"metar", "taf", "pirep"}:
            self.bounded(viewport, 20)
            params["bbox"] = (
                f"{viewport.south},{viewport.west},{viewport.north},{viewport.east}"
            )
        endpoints = [endpoint, "airsigmet"] if self.product == "sigmet" else [endpoint]
        features, unavailable = [], []
        for source in endpoints:
            try:
                data = self.http.json(
                    f"https://aviationweather.gov/api/data/{source}",
                    params=params,
                    cache_ttl=300,
                )
                if not isinstance(data, dict) or not isinstance(
                    data.get("features"), list
                ):
                    raise ProviderError("invalid_schema", "AWC features are missing")
                features.extend(data["features"])
            except ProviderError:
                unavailable.append(source)
        if len(unavailable) == len(endpoints):
            raise ProviderError("upstream_unavailable", "AWC products are unavailable")

        def parse(row):
            geometry, position, bounds = normalize_geometry(
                row.get("geometry"), max_points=150
            )
            props = row.get("properties") or {}
            source_time = next(
                (
                    props[k]
                    for k in (
                        "obsTime",
                        "receiptTime",
                        "reportTime",
                        "issueTime",
                        "validTimeFrom",
                        "validTime",
                        "time",
                        "date",
                    )
                    if props.get(k)
                ),
                None,
            )
            if source_time is None:
                raise ValueError("AWC record lacks source time")
            if isinstance(source_time, (int, float)) and source_time > 1e12:
                source_time /= 1000
            recorded = timestamp(source_time)
            ident = str(
                row.get("id")
                or (props.get("icaoId") if self.product in {"metar", "taf"} else None)
                or props.get("id")
                or hashlib.sha256(str(row).encode()).hexdigest()[:24]
            )
            value = self.observation(
                source_id=ident[:200],
                entity_type=self.product,
                position=position,
                observed_at=recorded,
                received_at=now,
                kind="predicted" if self.product in {"taf", "gairmet"} else "observed",
                properties={
                    "name": props.get("icaoId")
                    or props.get("id")
                    or props.get("station")
                    or self.product.upper(),
                    "product": self.product,
                    "raw_text": str(
                        props.get("rawOb")
                        or props.get("rawTAF")
                        or props.get("rawAirSigmet")
                        or props.get("rawSigmet")
                        or props.get("rawReport")
                        or ""
                    )[:8000],
                    "source_fields": props,
                    "geometry": geometry,
                    "spatial_bounds": bounds,
                },
            )
            return value if observation_in_view(value, viewport) else None

        values = self.normalize(features, parse)
        self.rejected += len(unavailable)
        self.status_message = (
            "Partial coverage; unavailable: " + ", ".join(unavailable)
            if unavailable
            else f"{len(values)} {self.product.upper()} reports in view"
        )
        return values
