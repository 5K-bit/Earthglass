"""Normalize Traccar JSON position forwarding. Device identity is credential-bound."""

from .models import Position


def normalize_forward(payload, expected_traccar_id):
    position = payload.get("position", payload)
    if not isinstance(position, dict):
        raise ValueError("Missing Traccar position")
    if str(position.get("deviceId")) != str(expected_traccar_id):
        raise ValueError("Traccar device does not match its registered credential")
    if position.get("valid") is not True:
        raise ValueError("Invalid GPS fix")
    attributes = position.get("attributes") or {}
    speed = position.get("speed")
    return Position(
        latitude=position["latitude"],
        longitude=position["longitude"],
        altitude_m=position.get("altitude"),
        accuracy_m=position.get("accuracy"),
        speed_mps=float(speed) * 0.514444444 if speed is not None else None,
        heading_deg=position.get("course"),
        battery_percent=attributes.get("batteryLevel"),
        moving=attributes.get("motion"),
        recorded_at=position["fixTime"],
    )
