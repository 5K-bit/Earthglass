"""The v1 spatial wire contract. Unknown fields and non-finite values are rejected."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(Contract):
    latitude: float = Field(ge=-90, le=90, strict=True)
    longitude: float = Field(ge=-180, le=180, strict=True)
    altitude_m: float | None = None
    altitude_reference: Literal["ellipsoid", "msl", "barometric", "unknown"] = "unknown"


class Motion(Contract):
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    speed_mps: float | None = Field(default=None, ge=0)
    vertical_rate_mps: float | None = None


class Confidence(Contract):
    value: float = Field(ge=0, le=1)
    method: str = Field(min_length=1, max_length=500)


class Provenance(Contract):
    provider: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=2000)
    attribution: str = Field(min_length=1, max_length=1000)
    license_url: str | None = None

    @field_validator("source_url", "license_url")
    @classmethod
    def safe_link(cls, value):
        if value is None:
            return value
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError(
                "Provenance links must be HTTPS URLs without embedded credentials"
            )
        return value


class Observation(Contract):
    schema_version: Literal["1.0"] = "1.0"
    entity_id: str = Field(min_length=1, max_length=250)
    layer: str = Field(min_length=1, max_length=60)
    entity_type: str = Field(min_length=1, max_length=60)
    position: Position
    motion: Motion | None = None
    observed_at: datetime
    received_at: datetime = Field(default_factory=utc_now)
    measurement_kind: Literal[
        "observed", "predicted", "simulated", "estimated", "catalog"
    ] = "observed"
    confidence: Confidence | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance

    @field_validator("observed_at", "received_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include its UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded_properties(self):
        if self.properties.get("spatial_bounds") is not None:
            Viewport.model_validate(self.properties["spatial_bounds"])
        encoded = json.dumps(self.properties, allow_nan=False)
        if len(encoded.encode("utf8")) > 32_768:
            raise ValueError("Observation properties exceed 32 KiB")
        return self

    def wire(self):
        return self.model_dump(mode="json")

    @property
    def observation_id(self):
        payload = self.model_dump(mode="json", exclude={"received_at"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class Viewport(Contract):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def ordered(self):
        if self.south > self.north:
            raise ValueError("south must not exceed north")
        return self

    def contains(self, position: Position):
        lon = position.longitude
        longitude_ok = (
            self.west <= lon <= self.east
            if self.west <= self.east
            else lon >= self.west or lon <= self.east
        )
        return self.south <= position.latitude <= self.north and longitude_ok

    @property
    def center(self):
        width = (
            self.east - self.west
            if self.east >= self.west
            else 360 + self.east - self.west
        )
        return (
            (self.south + self.north) / 2,
            (self.west + width / 2 + 180) % 360 - 180,
        )


class ProviderHealth(Contract):
    provider: str
    layer: str
    lifecycle: Literal["disabled", "idle", "loading", "running", "stopped"] = "disabled"
    state: Literal["online", "degraded", "stale", "offline", "recovering"] = "offline"
    count: int = 0
    rejected_records: int = 0
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    error_code: str | None = None
    message: str = "Not enabled"
    coverage: str = ""
    attribution: str = ""
    credential_required: str | None = None
    transport: Literal["snapshot", "polling", "websocket"] = "snapshot"
