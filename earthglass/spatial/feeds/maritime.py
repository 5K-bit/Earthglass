from __future__ import annotations

import json
from datetime import UTC, datetime

from ..network import ProviderError
from .base import Feed, ProviderSpec, number, timestamp


class VesselFeed(Feed):
    spec = ProviderSpec(
        "aisstream",
        "vessels",
        "Vessels",
        5,
        "AISStream receiver coverage in the selected area; public broadcasts are incomplete",
        "AISStream.io",
        credential="aisstream_api_key",
        transport="websocket",
    )
    source_url = "https://aisstream.io/"

    def parse_message(self, data, now):
        metadata = data.get("MetaData") or {}
        kind = data.get("MessageType")
        position = (data.get("Message") or {}).get(kind) or {}
        lat = number(position.get("Latitude"), number(metadata.get("latitude")))
        lon = number(position.get("Longitude"), number(metadata.get("longitude")))
        if lat is None or lon is None:
            return None
        mmsi = str(metadata.get("MMSI") or position.get("UserID") or "")
        if not mmsi:
            raise ValueError("MMSI is required")
        heading = number(position.get("TrueHeading"))
        if heading is None or heading >= 360:
            heading = number(position.get("Cog"))
        speed = number(position.get("Sog"))
        return self.observation(
            source_id=mmsi,
            entity_id=f"mmsi:{mmsi}",
            position={"latitude": lat, "longitude": lon},
            observed_at=timestamp(metadata.get("time_utc")),
            received_at=now,
            motion={
                "heading_deg": heading
                if heading is not None and 0 <= heading < 360
                else None,
                "speed_mps": speed * 0.514444
                if speed is not None and 0 <= speed < 102.3
                else None,
            },
            properties={
                "name": str(metadata.get("ShipName") or "").strip(),
                "mmsi": mmsi,
                "navigation_status": position.get("NavigationalStatus"),
            },
        )

    def run(self, viewport, emit, stop):
        key = self.key()
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise ProviderError(
                "dependency_missing", "Install EarthGlass's websockets dependency"
            ) from exc
        boxes = [[[viewport.south, viewport.west], [viewport.north, viewport.east]]]
        if viewport.west > viewport.east:
            boxes = [
                [[viewport.south, viewport.west], [viewport.north, 180]],
                [[viewport.south, -180], [viewport.north, viewport.east]],
            ]
        for area in getattr(self, "watch_viewports", []):
            if area.west <= area.east:
                boxes.append([[area.south, area.west], [area.north, area.east]])
            else:
                boxes.extend(
                    [
                        [[area.south, area.west], [area.north, 180]],
                        [[area.south, -180], [area.north, area.east]],
                    ]
                )
        with connect(
            "wss://stream.aisstream.io/v0/stream",
            open_timeout=10,
            close_timeout=2,
            max_size=1024 * 1024,
            max_queue=16,
        ) as connection:
            connection.send(
                json.dumps(
                    {
                        "APIKey": key,
                        "BoundingBoxes": boxes,
                        "FilterMessageTypes": [
                            "PositionReport",
                            "StandardClassBPositionReport",
                        ],
                    }
                )
            )
            while not stop.is_set():
                try:
                    raw = connection.recv(timeout=1)
                except TimeoutError:
                    emit([])  # Flush a quiet subscription at the same bounded cadence.
                    continue
                try:
                    data = json.loads(raw)
                    if "error" in data:
                        raise ProviderError(
                            "upstream_error", "AIS provider rejected the subscription"
                        )
                    value = self.parse_message(data, datetime.now(UTC))
                    if value:
                        emit([value])
                except (ValueError, TypeError, KeyError):
                    self.rejected += 1
