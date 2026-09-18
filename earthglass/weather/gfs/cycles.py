from __future__ import annotations

from datetime import datetime, timedelta, timezone

GFS_CYCLE_HOURS = (0, 6, 12, 18)


def as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def nominal_cycle(moment: datetime) -> datetime:
    utc = as_utc(moment)
    cycle_hour = max(hour for hour in GFS_CYCLE_HOURS if hour <= utc.hour)
    return utc.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)


def candidate_cycles(moment: datetime | None = None, count: int = 4) -> list[datetime]:
    if count < 1:
        raise ValueError("count must be at least 1")

    start = nominal_cycle(moment or datetime.now(timezone.utc))
    return [start - timedelta(hours=6 * offset) for offset in range(count)]


def cycle_id(cycle: datetime) -> str:
    utc = as_utc(cycle)
    return utc.strftime("%Y%m%d_%H")
