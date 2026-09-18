import type { Observation } from "./contracts";
export const label = (o: Observation) =>
  String(
    o.properties?.name ||
      o.properties?.callsign ||
      o.properties?.title ||
      o.properties?.place ||
      o.entity_id,
  );
