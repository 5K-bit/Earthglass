import type { Observation } from "./contracts";

// Animate only between two recent fixes. Never extrapolate a vehicle beyond its report.
export function canInterpolateTransit(
  previous: Observation | undefined,
  next: Observation,
  now = Date.now(),
) {
  if (
    !previous ||
    next.layer !== "transit_vehicles" ||
    previous.entity_id !== next.entity_id
  )
    return false;
  const start = Date.parse(previous.observed_at),
    end = Date.parse(next.observed_at);
  return (
    Number.isFinite(start) &&
    Number.isFinite(end) &&
    end > start &&
    end - start <= 120000 &&
    now - end >= -5000 &&
    now - end < 60000
  );
}
