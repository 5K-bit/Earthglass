import type { Observation } from "./contracts";
/** Event time is not delivery freshness: an older earthquake can be part of a fresh catalog. */
export function observationIsStale(o: Observation, now = Date.now()) {
  if (o.properties?.elements_stale) return true;
  const moving = [
    "aircraft",
    "military",
    "vessels",
    "satellites",
    "perception",
    "transit_vehicles",
    "traffic_speeds",
  ].includes(o.layer);
  const stamp = moving ? o.observed_at : (o.received_at ?? o.observed_at);
  const ttl =
    Number(o.properties?.retention_seconds) ||
    (o.layer === "transit_vehicles"
      ? 60
      : moving
        ? 180
        : o.layer === "weather" || o.layer === "temperature"
          ? 3600
          : 86400);
  return now - Date.parse(stamp) > ttl * 1000;
}

export function observationVisibleAt(o: Observation, at = Date.now()) {
  const props = o.properties ?? {};
  const sourceFields = props.source_fields as
    Record<string, unknown> | undefined;
  const end = props.expires ?? props.expected_end ?? sourceFields?.validTimeTo;
  if (
    typeof end === "string" &&
    Number.isFinite(Date.parse(end)) &&
    Date.parse(end) < at
  )
    return false;
  return true;
}
