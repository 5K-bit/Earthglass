"""GTFS-Realtime vehicle positions and alerts. Missing train GPS is never fabricated."""

from datetime import timedelta

from ..spatial.feeds.base import ProviderSpec, timestamp
from ..spatial.feeds.documents import DocumentFeed
from ..spatial.network import ProviderError

MTA_FEEDS = {
    "subway_ace": "nyct%2Fgtfs-ace",
    "subway_bdfm": "nyct%2Fgtfs-bdfm",
    "subway_g": "nyct%2Fgtfs-g",
    "subway_jz": "nyct%2Fgtfs-jz",
    "subway_nqrw": "nyct%2Fgtfs-nqrw",
    "subway_l": "nyct%2Fgtfs-l",
    "subway_1234567": "nyct%2Fgtfs",
    "staten_island": "nyct%2Fgtfs-si",
    "lirr": "lirr%2Fgtfs-lirr",
    "metro_north": "mnr%2Fgtfs-mnr",
    "alerts": "camsys%2Fall-alerts",
}


class GTFSRealtimeFeed(DocumentFeed):
    def __init__(
        self,
        http,
        credentials=lambda _: None,
        *,
        ident="mta_lirr",
        url=None,
        label="MTA LIRR",
        credential=None,
    ):
        super().__init__(http, credentials)
        self.endpoint = (
            url
            or "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/lirr%2Fgtfs-lirr"
        )
        self.source_url = (
            "https://www.mta.info/developers"
            if ident.startswith("mta_")
            else self.endpoint
        )
        self.spec = ProviderSpec(
            ident,
            "transit_alerts" if ident.endswith("_alerts") else "transit_vehicles",
            label,
            60,
            "GTFS-Realtime; only vehicles with actual coordinates are mapped. Station-only train updates remain service information.",
            "MTA" if ident.startswith("mta_") else label,
            credential=credential,
            max_records=5000,
        )

    def fetch(self, viewport, now):
        self.bounded(viewport, 15)
        from google.protobuf.message import DecodeError
        from google.transit import gtfs_realtime_pb2 as gtfs

        params = {"key": self.key()} if self.spec.credential else None
        body, _ = self.http.bytes(
            self.endpoint, params=params, max_bytes=8 * 1024 * 1024
        )
        message = gtfs.FeedMessage()
        try:
            message.ParseFromString(body)
        except DecodeError as exc:
            raise ProviderError(
                "invalid_gtfs", "Invalid GTFS-Realtime message"
            ) from exc
        if not message.IsInitialized() or not message.header.HasField("timestamp"):
            raise ProviderError("invalid_gtfs", "GTFS feed requires a source timestamp")
        if message.header.incrementality != gtfs.FeedHeader.FULL_DATASET:
            raise ProviderError(
                "differential_unsupported",
                "Differential feeds require a retained baseline",
            )
        source_time = timestamp(message.header.timestamp)
        if source_time > now + timedelta(minutes=5):
            raise ProviderError("future_data", "Transit source clock is in the future")
        alerts = []
        vehicles = []
        unlocated = 0
        updates = []

        def translated(value):
            return next(
                (
                    t.text
                    for t in value.translation
                    if t.language in {"en", "en-US", ""}
                ),
                next((t.text for t in value.translation), ""),
            )[:8000]

        for entity in message.entity[:10000]:
            if entity.is_deleted:
                continue
            if entity.HasField("alert"):
                alert = entity.alert
                alerts.append(
                    {
                        "id": entity.id,
                        "header": translated(alert.header_text),
                        "description": translated(alert.description_text),
                        "cause": gtfs.Alert.Cause.Name(alert.cause),
                        "effect": gtfs.Alert.Effect.Name(alert.effect),
                        "url": translated(alert.url),
                        "active_periods": [
                            {
                                "start": timestamp(p.start).isoformat()
                                if p.HasField("start")
                                else None,
                                "end": timestamp(p.end).isoformat()
                                if p.HasField("end")
                                else None,
                            }
                            for p in alert.active_period[:20]
                        ],
                        "routes": list(
                            dict.fromkeys(
                                v.route_id for v in alert.informed_entity if v.route_id
                            )
                        )[:100],
                        "source_time": source_time.isoformat(),
                    }
                )
            if entity.HasField("trip_update"):
                trip = entity.trip_update
                updates.append(
                    {
                        "trip_id": trip.trip.trip_id,
                        "route_id": trip.trip.route_id,
                        "stops": [
                            {
                                "stop_id": s.stop_id,
                                "arrival": timestamp(s.arrival.time).isoformat()
                                if s.HasField("arrival") and s.arrival.HasField("time")
                                else None,
                                "departure": timestamp(s.departure.time).isoformat()
                                if s.HasField("departure")
                                and s.departure.HasField("time")
                                else None,
                            }
                            for s in trip.stop_time_update[:10]
                        ],
                    }
                )
            if not entity.HasField("vehicle"):
                continue
            vehicle = entity.vehicle
            if (
                not vehicle.HasField("position")
                or not vehicle.position.HasField("latitude")
                or not vehicle.position.HasField("longitude")
            ):
                unlocated += 1
                continue
            try:
                position = vehicle.position
                observed = (
                    timestamp(vehicle.timestamp)
                    if vehicle.HasField("timestamp")
                    else source_time
                )
                value = self.observation(
                    source_id=vehicle.vehicle.id or entity.id,
                    position={
                        "latitude": position.latitude,
                        "longitude": position.longitude,
                    },
                    observed_at=observed,
                    received_at=now,
                    motion={
                        "speed_mps": position.speed
                        if position.HasField("speed")
                        else None,
                        "heading_deg": position.bearing % 360
                        if position.HasField("bearing")
                        else None,
                    },
                    properties={
                        "name": vehicle.vehicle.label
                        or vehicle.trip.route_id
                        or vehicle.vehicle.id,
                        "vehicle_id": vehicle.vehicle.id or entity.id,
                        "route_id": vehicle.trip.route_id or None,
                        "trip_id": vehicle.trip.trip_id or None,
                        "direction": vehicle.trip.direction_id
                        if vehicle.trip.HasField("direction_id")
                        else None,
                        "next_stop": vehicle.stop_id or None,
                        "status": gtfs.VehiclePosition.VehicleStopStatus.Name(
                            vehicle.current_status
                        ),
                        "timestamp_source": "vehicle"
                        if vehicle.HasField("timestamp")
                        else "feed",
                        "agency": self.spec.attribution,
                    },
                )
                if viewport.contains(value.position):
                    vehicles.append(value)
            except (ValueError, TypeError):
                self.rejected += 1
        if len(message.entity) > 10000:
            self.rejected += len(message.entity) - 10000
        self.status_message = f"{len(vehicles)} coordinate reports in view; {unlocated} vehicles without coordinates; {len(alerts)} service alerts"
        self.save_document(
            {
                "alerts": alerts[:1000],
                "trip_updates": updates[:1000],
                "unlocated_vehicles": unlocated,
                "source_time": source_time.isoformat(),
            },
            now,
        )
        if now - source_time > timedelta(minutes=10):
            self.rejected += 1
        return vehicles[: self.spec.max_records]


def default_transit(http, credentials):
    return [
        GTFSRealtimeFeed(
            http,
            credentials,
            ident="mta_" + key,
            url="https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" + path,
            label="MTA " + key.replace("_", " ").title(),
        )
        for key, path in MTA_FEEDS.items()
    ] + [
        GTFSRealtimeFeed(
            http,
            credentials,
            ident="mta_bus",
            url="https://gtfsrt.prod.obanyc.com/vehiclePositions",
            label="MTA Bus Time",
            credential="mta_bustime_api_key",
        )
    ]
