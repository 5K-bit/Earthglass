from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DeviceRegistration(PrivateModel):
    device_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    traccar_id: str = Field(min_length=1, max_length=100)
    tracking_enabled: bool = False
    retention_days: int = Field(default=30, ge=0, le=3650)


class DeviceUpdate(PrivateModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    tracking_enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=0, le=3650)


class Position(PrivateModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float | None = None
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    speed_mps: float | None = Field(default=None, ge=0, le=15000)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    moving: bool | None = None
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("UTC offset required")
        return value.astimezone(UTC)


class ViewerRegistration(PrivateModel):
    label: str = Field(min_length=1, max_length=100)
    devices: list[str] = Field(min_length=1, max_length=50)
    history: bool = False
    battery: bool = False
    expires_days: int = Field(default=30, ge=1, le=366)


class PresenceSettings(PrivateModel):
    enabled: bool = False
    live_seconds: int = Field(default=60, ge=15, le=600)
    recent_seconds: int = Field(default=300, ge=60, le=3600)
    stale_seconds: int = Field(default=1800, ge=300, le=86400)
