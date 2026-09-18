"""Local 3000 event projection. Camera position never claims a detected object's ground position."""

from ..network import ProviderError
from .base import Feed, ProviderSpec, number, timestamp


class PerceptionFeed(Feed):
    spec = ProviderSpec(
        "project3000",
        "perception",
        "3000 local perception",
        5,
        "Configured local cameras only; detections are located at the camera, not triangulated",
        "3000 local detector / operator-supplied camera locations",
        transport="polling",
        local=True,
    )
    source_url = "https://github.com/5K-bit/3000"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event_reader = None
        self.cameras = {}

    def configure(self, event_reader, cameras):
        self.event_reader = event_reader
        self.cameras = cameras

    def fetch(self, viewport, now):
        if not self.event_reader or not self.cameras:
            raise ProviderError(
                "camera_location_required",
                "Configure a 3000 camera location and event delivery in OBEOS",
            )

        def parse(event):
            payload = event.get("payload") or {}
            camera_id = str(payload.get("camera_id", ""))
            camera = self.cameras.get(camera_id)
            if not camera:
                return None
            position = {
                "latitude": float(camera["latitude"]),
                "longitude": float(camera["longitude"]),
            }
            observation = self.observation(
                source_id=event["event_id"],
                entity_id="3000:" + event["event_id"],
                entity_type="motion_detection",
                position=position,
                kind="estimated",
                observed_at=timestamp(event["timestamp"]),
                received_at=now,
                properties={
                    "name": "Motion at " + str(camera.get("label") or camera_id),
                    "camera_id": camera_id,
                    "event_id": event["event_id"],
                    "location_basis": "operator-configured camera location; object position is unknown",
                    "detector_score": number(payload.get("confidence")),
                    "detector_score_meaning": "3000 motion score; not object-classification probability",
                    "image_regions": (payload.get("metadata") or {}).get("regions"),
                    "camera_pose": "uncalibrated",
                },
            )
            return observation if viewport.contains(observation.position) else None

        return self.normalize(list(self.event_reader(500)), parse)
