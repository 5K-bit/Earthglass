import type { Observation, Viewport } from "./contracts";
function spans(west: number, east: number): [number, number][] {
  return west <= east
    ? [[west, east]]
    : [
        [west, 180],
        [-180, east],
      ];
}
export function inViewport(o: Observation, view: Viewport) {
  const bounds = o.properties?.spatial_bounds as Viewport | undefined;
  const area = bounds ?? {
    west: o.position.longitude,
    east: o.position.longitude,
    south: o.position.latitude,
    north: o.position.latitude,
  };
  return (
    area.south <= view.north &&
    area.north >= view.south &&
    spans(area.west, area.east).some(([a, b]) =>
      spans(view.west, view.east).some(([c, d]) => a <= d && b >= c),
    )
  );
}
export function selectVisibleDetail(
  sorted: Observation[],
  budget: number,
  selected: string | null,
) {
  const pinned = sorted.find((o) => o.entity_id === selected);
  const context = sorted
    .filter((o) =>
      ["LineString", "Polygon", "MultiPolygon"].includes(
        String((o.properties?.geometry as { type?: string } | undefined)?.type),
      ),
    )
    .slice(0, Math.min(100, Math.ceil(budget / 4)));
  const result = new Map<string, Observation>();
  if (pinned) result.set(pinned.entity_id, pinned);
  for (const o of context) if (result.size < budget) result.set(o.entity_id, o);
  for (const o of sorted) {
    if (result.size >= budget) break;
    result.set(o.entity_id, o);
  }
  return [...result.values()];
}
