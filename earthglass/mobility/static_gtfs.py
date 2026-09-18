"""Offline routes/stops imported from bounded GTFS ZIP archives; no schedule simulation."""

import csv
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from ..spatial.feeds.base import Feed, ProviderSpec
from ..spatial.geometry import normalize_geometry, observation_in_view
from ..spatial.models import Observation
from ..spatial.network import ProviderError


def import_gtfs(body, *, agency, source_url, attribution):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", agency):
        raise ValueError("Invalid agency identifier")
    if len(body) > 64 * 1024 * 1024:
        raise ValueError("GTFS archive exceeds 64 MiB")
    now = datetime.now(UTC)
    feed = StaticGTFSFeed(None)
    feed.source_url = source_url
    from dataclasses import replace

    feed.spec = replace(feed.spec, attribution=attribution)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        allowed = {
            "routes.txt",
            "trips.txt",
            "shapes.txt",
            "stops.txt",
            "feed_info.txt",
        }
        members = {i.filename: i for i in archive.infolist() if i.filename in allowed}
        if "routes.txt" not in members or "stops.txt" not in members:
            raise ValueError(
                "GTFS routes.txt and stops.txt are required at archive root"
            )
        if sum(i.file_size for i in members.values()) > 128 * 1024 * 1024:
            raise ValueError("Expanded GTFS tables exceed 128 MiB")

        def rows(name):
            if name not in members:
                return []
            with archive.open(name) as stream:
                reader = csv.DictReader(
                    io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
                )
                result = []
                for row in reader:
                    if len(result) >= 500000:
                        raise ValueError("GTFS table exceeds 500,000 rows")
                    if any(len(str(value)) > 8192 for value in row.values()):
                        raise ValueError("GTFS field is too large")
                    result.append(row)
                return result

        routes = {r["route_id"]: r for r in rows("routes.txt")}
        if len(routes) > 2000:
            raise ValueError("GTFS route limit exceeded")
        shape_routes = {}
        for trip in rows("trips.txt"):
            if trip.get("shape_id") and trip.get("route_id") in routes:
                shape_routes.setdefault(trip["shape_id"], set()).add(trip["route_id"])
        shapes = {}
        for point in rows("shapes.txt"):
            if point["shape_id"] in shape_routes:
                shapes.setdefault(point["shape_id"], []).append(
                    (
                        int(point["shape_pt_sequence"]),
                        float(point["shape_pt_lon"]),
                        float(point["shape_pt_lat"]),
                    )
                )
        observations = []
        for shape, points in shapes.items():
            if len(observations) >= 3000:
                break
            geometry, position, bounds = normalize_geometry(
                {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for _, lon, lat in sorted(points)],
                },
                max_points=200,
            )
            for route_id in sorted(shape_routes[shape])[:5]:
                route = routes[route_id]
                observations.append(
                    feed.observation(
                        source_id=agency + ":" + route_id + ":" + shape,
                        position=position,
                        observed_at=now,
                        received_at=now,
                        kind="catalog",
                        properties={
                            "name": route.get("route_short_name")
                            or route.get("route_long_name")
                            or route_id,
                            "route_id": route_id,
                            "agency": agency,
                            "route_type": route.get("route_type"),
                            "geometry": geometry,
                            "spatial_bounds": bounds,
                            "meaning": "Imported static GTFS route; temporary diversions may differ",
                        },
                    ).wire()
                )
        stops = rows("stops.txt")
        if len(stops) > 10000:
            raise ValueError("Import an area with at most 10,000 stops")
        for stop in stops:
            value = feed.observation(
                source_id=agency + ":stop:" + stop["stop_id"],
                position={
                    "latitude": float(stop["stop_lat"]),
                    "longitude": float(stop["stop_lon"]),
                },
                observed_at=now,
                received_at=now,
                kind="catalog",
                entity_type="transit_stop",
                properties={
                    "name": stop.get("stop_name"),
                    "stop_id": stop["stop_id"],
                    "agency": agency,
                    "meaning": "Imported stop location; no live arrival claim",
                },
            )
            value.layer = "transit_stops"
            observations.append(value.wire())
        if not observations:
            raise ValueError("No geographic GTFS routes or stops")
        return {
            "agency": agency,
            "imported_at": now.isoformat(),
            "source_url": source_url,
            "attribution": attribution,
            "route_count": len(routes),
            "stop_count": len(stops),
            "feed_info": rows("feed_info.txt")[:5],
            "observations": observations,
            "routes": [
                {
                    k: r.get(k)
                    for k in (
                        "route_id",
                        "route_short_name",
                        "route_long_name",
                        "route_type",
                    )
                }
                for r in routes.values()
            ],
        }


class StaticGTFSFeed(Feed):
    source_url = "https://gtfs.org/documentation/schedule/reference/"

    def __init__(self, http, credentials=lambda _: None, *, stops=False):
        super().__init__(http, credentials)
        self.spec = ProviderSpec(
            "local_gtfs_stops" if stops else "local_gtfs",
            "transit_stops" if stops else "transit_routes",
            "Imported GTFS " + ("stops" if stops else "routes"),
            60,
            "Local imported public GTFS; available offline; schedules and temporary detours are not inferred",
            "GTFS source attribution is carried on each record",
            local=True,
            max_records=10000,
        )

    def configure_cache(self, directory):
        super().configure_cache(directory)
        self._directory = Path(directory) / "transit"

    def documents(self):
        values = []
        for path in sorted(self._directory.glob("*.json"))[:12]:
            try:
                if path.stat().st_size > 32 * 1024 * 1024:
                    continue
                values.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return values

    def fetch(self, viewport, now):
        documents = self.documents()
        if not documents:
            raise ProviderError(
                "import_required",
                "Import a public GTFS ZIP to use local routes and stops offline",
            )
        values = []
        for document in documents:
            for raw in document.get("observations", []):
                if raw.get("layer") != self.spec.layer:
                    continue
                try:
                    value = Observation.model_validate(raw)
                    if observation_in_view(value, viewport):
                        values.append(value)
                except ValueError:
                    self.rejected += 1
        return values[: self.spec.max_records]

    def install(self, document):
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / (document["agency"] + ".json")
        if not path.exists() and len(list(self._directory.glob("*.json"))) >= 12:
            raise ValueError("Maximum 12 imported transit areas")
        encoded = json.dumps(document, allow_nan=False)
        if len(encoded.encode()) > 32 * 1024 * 1024:
            raise ValueError("Imported route data exceeds 32 MiB")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(path)
        return {
            k: v for k, v in document.items() if k not in {"observations", "routes"}
        }
