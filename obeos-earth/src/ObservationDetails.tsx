import type { Observation } from "./contracts";
const fields: Record<string, string> = {
  magnitude: "Magnitude",
  depth_m: "Depth (m)",
  place: "Location",
  event: "Alert",
  severity: "Severity",
  certainty: "Certainty",
  urgency: "Urgency",
  effective: "Effective",
  expires: "Expires",
  areaDesc: "Area",
  temperature_c: "Temperature (°C)",
  wind_speed_mps: "Wind (m/s)",
  precipitation_mm: "Precipitation (mm)",
  pressure_pa: "Pressure (Pa)",
  cloud_cover_percent: "Cloud cover (%)",
  brightness_k: "Brightness (K)",
  frp_mw: "Radiative power (MW)",
  provider_confidence: "Source confidence",
  satellite: "Satellite",
  norad_id: "NORAD ID",
  group: "Orbital group",
  elements_retrieved_at: "Elements downloaded",
  route_id: "Route",
  vehicle_id: "Vehicle",
  trip_id: "Trip",
  next_stop: "Next stop",
  destination: "Destination",
  direction: "Direction",
  road: "Road",
  type: "Type",
  full_closure: "Full closure",
  lanes_affected: "Lanes affected",
  source_speed: "Source speed (unit unconfirmed)",
  source_travel_time: "Source travel time (unit unconfirmed)",
  congestion: "Congestion",
  zone_derived: "Uses affected-zone geometry",
  unmapped_zones: "Zones awaiting geometry",
  expected_end: "Expected end",
};
export function ObservationDetails({
  observation,
}: {
  observation: Observation;
}) {
  const props = observation.properties ?? {};
  const cameraViews = (Array.isArray(props.views) ? props.views : []) as {
    id?: string | number;
    label?: string;
    url?: string | null;
    status?: string;
  }[];
  const link = (value: unknown): string | null =>
    typeof value === "string" && value.startsWith("https://") ? value : null;
  return (
    <section className="observation-details">
      <dl>
        <dt>Evidence type</dt>
        <dd>{observation.measurement_kind}</dd>
        {Object.entries(fields)
          .filter(([key]) => props[key] !== undefined)
          .map(([key, title]) => (
            <div className="detail-field" key={key}>
              <dt>{title}</dt>
              <dd>
                {props[key] === null
                  ? "Unknown"
                  : typeof props[key] === "boolean"
                    ? props[key]
                      ? "Yes"
                      : "No"
                    : String(props[key])}
              </dd>
            </div>
          ))}
      </dl>
      {["description", "instructions", "meaning", "raw_text"].map((key) =>
        typeof props[key] === "string" && props[key] ? (
          <p key={key} style={{ whiteSpace: "pre-wrap" }}>
            {String(props[key])}
          </p>
        ) : null,
      )}
      {cameraViews.map((view, i) =>
        link(view.url) ? (
          <p key={String(view.id ?? i)}>
            <a href={link(view.url)!} rel="noreferrer" target="_blank">
              Open official camera · {view.label ?? view.status ?? "View"}
            </a>
          </p>
        ) : null,
      )}
      {props.stream_type === "official_page" && link(props.public_view_url) && (
        <a href={link(props.public_view_url)!} target="_blank" rel="noreferrer">
          Open official public camera map
        </a>
      )}
    </section>
  );
}
