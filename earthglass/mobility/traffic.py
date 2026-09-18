"""Public NYC sensor and 511NY incident/camera adapters."""

import csv
import io
import hashlib
import ipaddress
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from ..spatial.feeds.base import Feed, ProviderSpec, number, timestamp
from ..spatial.geometry import normalize_geometry, observation_in_view


def decode_polyline(encoded):
    if not isinstance(encoded, str) or len(encoded) > 20000:
        raise ValueError("Invalid polyline")
    result = []
    index = 0
    lat = lon = 0
    while index < len(encoded) and len(result) < 2000:
        values = []
        for _ in range(2):
            shift = value = 0
            while True:
                if index >= len(encoded) or shift > 30:
                    raise ValueError("Invalid polyline")
                digit = ord(encoded[index]) - 63
                index += 1
                if not 0 <= digit <= 63:
                    raise ValueError("Invalid polyline character")
                value |= (digit & 31) << shift
                shift += 5
                if digit < 32:
                    break
            values.append(~(value >> 1) if value & 1 else value >> 1)
        lat += values[0]
        lon += values[1]
        result.append([lon / 1e5, lat / 1e5])
    return result


def public_link(value):
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname or ""
        if host.lower() in {
            "localhost",
            "localhost.localdomain",
        } or host.lower().endswith((".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        if any(
            any(
                term in name.lower()
                for term in ("key", "token", "secret", "auth", "signature")
            )
            for name, _ in parse_qsl(parsed.query)
        ):
            return None
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return str(value)
    except ValueError:
        pass
    return None


class NYCDOTFeed(Feed):
    spec = ProviderSpec(
        "nyc_dot",
        "traffic_speeds",
        "NYC DOT traffic sensors",
        60,
        "NYC arterial/highway sensors; outages and incomplete coverage. Source speed units are unconfirmed and remain explicit raw values.",
        "City of New York Department of Transportation",
        license_url="https://www.nyc.gov/html/dot/html/about/datafeeds.shtml",
    )
    source_url = "https://www.nyc.gov/html/dot/html/about/datafeeds.shtml"

    def fetch(self, viewport, now):
        self.bounded(viewport, 12)
        text = self.http.text("https://linkdata.nyctmc.org/data/LinkSpeedQuery.txt")
        rows = list(csv.DictReader(io.StringIO(text), delimiter="	"))

        def parse(row):
            observed = datetime.strptime(row["DataAsOf"], "%m/%d/%Y %H:%M:%S").replace(
                tzinfo=ZoneInfo("America/New_York")
            )
            if now - observed > timedelta(days=1):
                self.rejected += 1
                return None
            points = decode_polyline(row["EncodedPolyLine"])
            geometry, position, bounds = normalize_geometry(
                {"type": "LineString", "coordinates": points}, max_points=150
            )
            raw_speed = number(row.get("Speed"))
            raw_travel = number(row.get("TravelTime"))
            # Sensor status is not a verified congestion category. Missing baseline/units stay null.
            value = self.observation(
                source_id=row["linkId"],
                position=position,
                observed_at=observed,
                received_at=now,
                properties={
                    "name": row.get("linkName"),
                    "borough": row.get("Borough"),
                    "geometry": geometry,
                    "spatial_bounds": bounds,
                    "speed_mps": None,
                    "expected_speed_mps": None,
                    "travel_time_seconds": None,
                    "source_speed": raw_speed,
                    "source_speed_unit": "unconfirmed",
                    "source_travel_time": raw_travel,
                    "source_travel_time_unit": "unconfirmed",
                    "source_status": row.get("Status"),
                    "congestion": "unknown",
                    "sensor_available": raw_travel is not None and raw_travel > 0,
                    "meaning": "Source units pending confirmation; zero/missing sensor values are not labeled stopped traffic",
                },
            )
            return value if observation_in_view(value, viewport) else None

        return self.normalize(rows, parse)


def normalize_incident_type(value):
    text = str(value or "").lower()
    for terms, kind in [
        (("collision", "accident", "crash"), "collision"),
        (("closure", "closed"), "road_closure"),
        (("disabled", "broken down"), "disabled_vehicle"),
        (("construction", "roadwork"), "construction"),
        (("weather", "winter", "snow", "ice", "flood"), "weather_condition"),
        (("police",), "police_activity"),
        (("special event",), "special_event"),
        (("hazard", "debris"), "hazard"),
    ]:
        if any(term in text for term in terms):
            return kind
    return "other"


class NY511Feed(Feed):
    source_url = "https://511ny.org/developers/doc"

    def __init__(self, http, credentials=lambda _: None, *, product="incidents"):
        super().__init__(http, credentials)
        if product not in {"incidents", "cameras", "conditions"}:
            raise ValueError("Unsupported 511 product")
        self.product = product
        self.spec = ProviderSpec(
            "ny511_" + product,
            "cctv" if product == "cameras" else "traffic_incidents",
            "511NY " + product,
            180,
            "New York State official public "
            + product
            + "; optional free developer key; ten calls per minute shared source limit",
            "511NY / NYSDOT",
            credential="ny511_api_key",
            max_records=5000,
        )

    def fetch(self, viewport, now):
        self.bounded(viewport, 20)
        endpoint = {
            "incidents": "event",
            "cameras": "cameras",
            "conditions": "winterroads",
        }[self.product]
        rows = self.http.json(
            "https://511ny.org/api/"
            + ("v3" if self.product == "conditions" else "v2")
            + "/get/"
            + endpoint,
            params={"key": self.key(), "format": "json"},
            cache_ttl=180,
        )

        if self.product == "conditions" and isinstance(rows, list):
            expanded = []
            for row in rows[: self.spec.max_records]:
                if not isinstance(row, dict):
                    continue
                lines = row.get("EncodedPolyline", [])
                lines = lines if isinstance(lines, list) else [lines]
                ident = str(
                    row.get("Id")
                    or hashlib.sha256(
                        (
                            str(row.get("RoadwayName"))
                            + "|"
                            + str(row.get("LocationDescription"))
                        ).encode()
                    ).hexdigest()[:24]
                )
                for index, line in enumerate(lines[:8]):
                    expanded.append(
                        {**row, "Id": f"{ident}:{index}", "EncodedPolyline": line}
                    )
            rows = expanded

        def parse(row):
            geometry = bounds = None
            if row.get("EncodedPolyline"):
                geometry, point, bounds = normalize_geometry(
                    {
                        "type": "LineString",
                        "coordinates": decode_polyline(row["EncodedPolyline"]),
                    },
                    max_points=150,
                )
            else:
                point = {
                    "latitude": float(row["Latitude"]),
                    "longitude": float(row["Longitude"]),
                }
            if self.product == "cameras":
                views = [
                    {
                        "id": v.get("Id"),
                        "label": v.get("Description"),
                        "url": public_link(v.get("Url")),
                        "video_url": public_link(v.get("VideoUrl")),
                        "status": v.get("Status"),
                    }
                    for v in (row.get("Views") or [])[:8]
                ]
                return self.observation(
                    source_id=str(row["Id"]),
                    position=point,
                    observed_at=now,
                    received_at=now,
                    kind="catalog",
                    properties={
                        "name": row.get("Location"),
                        "road": row.get("Roadway"),
                        "direction": row.get("Direction"),
                        "views": views,
                        "public_view_url": "https://511ny.org/",
                        "stream_type": "official_page",
                        "pose_estimated": True,
                        "meaning": "Official camera catalog; source may require opening its player; no image-time claim",
                    },
                )
            observed = timestamp(row.get("LastUpdated") or row.get("Reported"))
            end = (
                timestamp(row["PlannedEndDate"]) if row.get("PlannedEndDate") else None
            )
            if end and end < now:
                return None
            props = {
                "name": row.get("RoadwayName") or row.get("Location"),
                "type": "weather_condition"
                if self.product == "conditions"
                else (
                    "road_closure"
                    if row.get("IsFullClosure")
                    else normalize_incident_type(row.get("EventType"))
                ),
                "source_type": row.get("EventType"),
                "road_conditions": row.get("Condition")
                if self.product == "conditions"
                else None,
                "visibility": row.get("Visibility"),
                "drifting": row.get("Drifting"),
                "location_description": row.get("LocationDescription"),
                "subtype": row.get("EventSubType"),
                "severity": row.get("Severity"),
                "road": row.get("RoadwayName"),
                "direction": row.get("DirectionOfTravel"),
                "description": str(
                    row.get("Description") or row.get("Condition") or ""
                )[:8000],
                "started_at": timestamp(row["StartDate"]).isoformat()
                if row.get("StartDate")
                else None,
                "updated_at": observed.isoformat(),
                "expected_end": end.isoformat() if end else None,
                "full_closure": row.get("IsFullClosure"),
                "lanes_affected": row.get("LanesAffected"),
            }
            if geometry:
                props.update(geometry=geometry, spatial_bounds=bounds)
            value = self.observation(
                source_id=str(row.get("ID", row.get("Id"))),
                position=point,
                observed_at=observed,
                received_at=now,
                properties=props,
            )
            return value if observation_in_view(value, viewport) else None

        return self.normalize(rows, parse)
