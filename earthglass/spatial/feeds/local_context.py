from __future__ import annotations

from urllib.parse import urlsplit

from ..network import ProviderError
from .base import Feed, ProviderSpec, number, timestamp


class InfrastructureFeed(Feed):
    spec = ProviderSpec(
        "overpass",
        "infrastructure",
        "Infrastructure",
        3600,
        "Viewport-bounded OSM mapped infrastructure; incomplete catalog",
        "© OpenStreetMap contributors",
        max_records=2000,
        license_url="https://www.openstreetmap.org/copyright",
    )
    source_url = "https://www.openstreetmap.org/"
    selection = 'nwr["power"~"^(plant|substation)$"];nwr["waterway"="dam"];nwr["telecom"="data_center"];nwr["aeroway"="aerodrome"];'

    def fetch(self, viewport, now):
        self.bounded(viewport, 5)
        area = f"{viewport.south},{viewport.west},{viewport.north},{viewport.east}"
        query = f"[out:json][timeout:10][bbox:{area}];({self.selection});out center geom {self.spec.max_records};"
        data = None
        for endpoint in (
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
        ):
            try:
                candidate = self.http.json(endpoint, method="POST", data={"data": query})
                if candidate.get("remark"):
                    raise ProviderError("upstream_query_failed", "OSM query timed out or exceeded source resources")
                data = candidate
                break
            except ProviderError:
                continue
        if data is None:
            raise ProviderError(
                "upstream_unavailable", "OSM query providers are unavailable"
            )

        def parse(row):
            center = row.get("center") or row
            if "lat" not in center or "lon" not in center:
                bounds = row.get("bounds")
                if bounds:
                    center = {
                        "lat": (bounds["minlat"] + bounds["maxlat"]) / 2,
                        "lon": (bounds["minlon"] + bounds["maxlon"]) / 2,
                    }
                else:
                    points = [
                        p
                        for p in row.get("geometry", [])[:500]
                        if p
                        and number(p.get("lat")) is not None
                        and number(p.get("lon")) is not None
                    ]
                    if not points:
                        return None
                    center = {
                        "lat": sum(p["lat"] for p in points) / len(points),
                        "lon": sum(p["lon"] for p in points) / len(points),
                    }
            tags = row.get("tags") or {}
            return self.observation(
                source_id=f"{row['type']}:{row['id']}",
                position={
                    "latitude": float(center["lat"]),
                    "longitude": float(center["lon"]),
                },
                observed_at=timestamp(
                    (data.get("osm3s") or {}).get("timestamp_osm_base"), fallback=now
                ),
                received_at=now,
                kind="catalog",
                properties={
                    "name": tags.get("name"),
                    "tags": {
                        str(key): str(value)[:256]
                        for key, value in list(tags.items())[:30]
                    },
                    "position_basis": "Representative catalog position; geometry centroid when source center is absent",
                    "meaning": "Mapped infrastructure; no inference of current activity",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [point["lon"], point["lat"]]
                            for point in row.get("geometry", [])[:500]
                            if point and "lon" in point and "lat" in point
                        ],
                    }
                    if row.get("geometry")
                    else None,
                },
                source_url=f"https://www.openstreetmap.org/{row['type']}/{row['id']}",
            )

        return self.normalize(data.get("elements"), parse)


class TrafficFeed(InfrastructureFeed):
    spec = ProviderSpec(
        "traffic",
        "traffic",
        "Road network",
        3600,
        "Viewport-bounded OSM roads; catalog geometry, not live congestion or transit arrivals",
        "© OpenStreetMap contributors",
        max_records=1000,
        license_url="https://www.openstreetmap.org/copyright",
    )
    selection = 'way["highway"~"^(motorway|trunk|primary|secondary)$"];'

    def fetch(self, viewport, now):
        roads = super().fetch(viewport, now)
        for road in roads:
            road.properties["traffic_state"] = "catalog"
            road.properties["meaning"] = "Stored road geometry; no live congestion estimate"
            road.provenance.provider = "overpass_roads"
        return roads


class BikeshareFeed(Feed):
    spec = ProviderSpec(
        "citibike",
        "bikeshare",
        "Bikeshare",
        60,
        "Citi Bike stations in New York / New Jersey",
        "Citi Bike / Lyft GBFS",
        transport="polling",
        license_url="https://citibikenyc.com/data-sharing-policy",
    )
    source_url = "https://citibikenyc.com/system-data"
    discovery_url = "https://gbfs.citibikenyc.com/gbfs/gbfs.json"

    def fetch(self, viewport, now):
        discovery = self.http.json(self.discovery_url, cache_ttl=3600)
        data = discovery.get("data") or {}
        section = (
            data if "feeds" in data else data.get("en", next(iter(data.values()), {}))
        )
        feeds = {row["name"]: row["url"] for row in section.get("feeds", [])}
        info = self.http.json(feeds["station_information"], cache_ttl=3600)
        status = self.http.json(feeds["station_status"], cache_ttl=60)
        statuses = {row["station_id"]: row for row in status["data"]["stations"]}

        def parse(row):
            state = statuses.get(row["station_id"])
            observed = (
                timestamp(
                    state.get("last_reported"),
                    fallback=timestamp(status.get("last_updated"), fallback=now),
                )
                if state
                else now
            )
            value = self.observation(
                source_id=str(row["station_id"]),
                position={
                    "latitude": float(row["lat"]),
                    "longitude": float(row["lon"]),
                },
                observed_at=observed,
                received_at=now,
                kind="observed" if state else "catalog",
                properties={
                    "name": row.get("name"),
                    "capacity": row.get("capacity"),
                    "bikes_available": state.get("num_bikes_available")
                    if state
                    else None,
                    "docks_available": state.get("num_docks_available")
                    if state
                    else None,
                    "renting": bool(state.get("is_renting")) if state else None,
                },
            )
            return value if viewport.contains(value.position) else None

        return self.normalize(info["data"]["stations"], parse)


class TfLCameraFeed(Feed):
    spec = ProviderSpec(
        "tfl",
        "cctv",
        "Public cameras",
        1800,
        "TfL JamCams in London; frames are periodically updated, poses are uncalibrated",
        "Powered by TfL Open Data. Contains OS data © Crown copyright and database rights",
        license_url="https://tfl.gov.uk/info-for/open-data-users/",
    )
    source_url = "https://tfl.gov.uk/"

    def fetch(self, viewport, now):
        rows = self.http.json("https://api.tfl.gov.uk/Place/Type/JamCam", cache_ttl=self.spec.interval_seconds)

        def parse(row):
            properties = {
                item.get("key"): item.get("value")
                for item in row.get("additionalProperties", [])
            }
            image = properties.get("imageUrl")
            if image and urlsplit(image).scheme != "https":
                image = None
            value = self.observation(
                source_id=row["id"],
                entity_type="camera",
                position={
                    "latitude": float(row["lat"]),
                    "longitude": float(row["lon"]),
                },
                observed_at=now,
                received_at=now,
                kind="catalog",
                properties={
                    "name": row.get("commonName"),
                    "image_url": image,
                    "video_url": properties.get("videoUrl"),
                    "pose": "uncalibrated",
                    "camera_status": properties.get("status"),
                    "media_mode": "periodic public frames",
                },
            )
            return value if viewport.contains(value.position) else None

        return self.normalize(rows, parse)


class CaltransCameraFeed(Feed):
    source_url = "https://cwwp2.dot.ca.gov/"

    def __init__(self, http, credentials=lambda _: None, *, district=4):
        super().__init__(http, credentials)
        self.district = district
        self.spec = ProviderSpec(
            f"caltrans_d{district}",
            "cctv",
            f"Caltrans district {district}",
            1800,
            f"California public traffic cameras, district {district}; uncalibrated poses",
            "Caltrans — cwwp2.dot.ca.gov",
        )

    def fetch(self, viewport, now):
        data = self.http.json(
            f"https://cwwp2.dot.ca.gov/data/d{self.district}/cctv/cctvStatusD{self.district:02}.json",
            cache_ttl=self.spec.interval_seconds,
        )

        def parse(item):
            row = item.get("cctv", item)
            location = row.get("location") or {}
            image = (row.get("imageData") or {}).get("static") or {}
            current = image.get("currentImageURL")
            value = self.observation(
                source_id=str(location.get("locationName") or row["index"]),
                entity_type="camera",
                position={
                    "latitude": float(location["latitude"]),
                    "longitude": float(location["longitude"]),
                },
                observed_at=now,
                received_at=now,
                kind="catalog",
                properties={
                    "name": location.get("locationName"),
                    "image_url": current,
                    "pose": "uncalibrated",
                    "camera_status": row.get("inService"),
                    "media_mode": "periodic public frames",
                },
            )
            return value if viewport.contains(value.position) else None

        return self.normalize(data.get("data"), parse)
