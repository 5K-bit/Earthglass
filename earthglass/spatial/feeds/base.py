from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ..models import Observation, Viewport
from ..network import ProviderError


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    layer: str
    label: str
    interval_seconds: int
    coverage: str
    attribution: str
    credential: str | None = None
    transport: str = "snapshot"
    max_records: int = 5000
    license_url: str | None = None
    local: bool = False


class SnapshotProvider(Protocol):
    spec: ProviderSpec

    def fetch(self, viewport: Viewport, now: datetime) -> list[Observation]: ...


class StreamingProvider(Protocol):
    spec: ProviderSpec

    def run(self, viewport: Viewport, emit: Callable, stop): ...


def number(value, default=None):
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def timestamp(value, *, fallback=None):
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Source timestamp requires a UTC offset")
            return parsed.astimezone(UTC)
        except ValueError:
            try:
                return datetime.strptime(
                    value, "%Y-%m-%d %H:%M:%S.%f %z UTC"
                ).astimezone(UTC)
            except ValueError:
                pass
    if fallback is not None:
        return fallback
    raise ValueError("Missing source timestamp")


class Feed:
    def __init__(self, http, credentials=lambda _: None):
        self.http = http
        self.credentials = credentials
        self.rejected = 0

    def configure_cache(self, directory):
        """Optional disk cache for public, non-credential provider material."""
        self.cache_directory = directory

    def key(self):
        key = self.credentials(self.spec.credential) if self.spec.credential else None
        if self.spec.credential and not key:
            raise ProviderError(
                "credential_required",
                f"Configure {self.spec.credential} in Blackfong provider settings",
            )
        return key

    def normalize(self, rows, parse):
        if not isinstance(rows, list):
            raise ProviderError("invalid_schema", "Provider list is missing")
        self.rejected = max(0, len(rows) - self.spec.max_records)
        observations = []
        for row in rows[: self.spec.max_records]:
            try:
                value = parse(row)
                if value is not None:
                    observations.append(value)
            except (ValueError, KeyError, TypeError, IndexError, OverflowError):
                self.rejected += 1
        if (
            rows
            and not observations
            and self.rejected - max(0, len(rows) - self.spec.max_records)
            >= min(len(rows), self.spec.max_records)
        ):
            raise ProviderError(
                "invalid_records", "All provider records failed validation"
            )
        return observations

    def observation(
        self,
        *,
        source_id,
        entity_id=None,
        position,
        observed_at,
        received_at,
        properties=None,
        motion=None,
        kind="observed",
        entity_type=None,
        source_url=None,
    ):
        return Observation(
            entity_id=entity_id or f"{self.spec.id}:{source_id}",
            layer=self.spec.layer,
            entity_type=entity_type or self.spec.layer,
            position=position,
            motion=motion,
            observed_at=observed_at,
            received_at=received_at,
            measurement_kind=kind,
            properties=properties or {},
            provenance={
                "provider": self.spec.id,
                "source_id": str(source_id),
                "source_url": source_url or self.source_url,
                "attribution": self.spec.attribution,
                "license_url": self.spec.license_url,
            },
        )

    def bounded(self, viewport, degrees=10):
        width = (
            viewport.east - viewport.west
            if viewport.east >= viewport.west
            else 360 + viewport.east - viewport.west
        )
        if width > degrees or viewport.north - viewport.south > degrees:
            raise ProviderError(
                "zoom_required",
                f"Zoom to an area smaller than {degrees} degrees for this layer",
            )
        if viewport.west > viewport.east:
            raise ProviderError(
                "dateline_viewport", "Split this provider's query at the date line"
            )
