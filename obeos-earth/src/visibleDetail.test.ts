import { it, expect } from "vitest";
import { inViewport, selectVisibleDetail } from "./visibleDetail";
import type { Observation } from "./contracts";
function item(id: string, geometry = false) {
  return {
    entity_id: id,
    position: { latitude: 41, longitude: -74 },
    properties: geometry
      ? {
          geometry: { type: "LineString" },
          spatial_bounds: { west: -75, east: -73, south: 40, north: 42 },
        }
      : {},
  } as Observation;
}
it("keeps intersecting routes and selected objects when dense stops fill the budget", () => {
  const stops = Array.from({ length: 1000 }, (_, i) => item("stop" + i));
  const route = item("route", true);
  const result = selectVisibleDetail([...stops, route], 200, "stop999");
  expect(result.length).toBe(200);
  expect(result).toContain(route);
  expect(result[0].entity_id).toBe("stop999");
  expect(
    inViewport(route, { west: -73.5, east: -73.2, south: 41.5, north: 41.8 }),
  ).toBe(true);
  expect(
    inViewport(stops[0], {
      west: -73.5,
      east: -73.2,
      south: 41.5,
      north: 41.8,
    }),
  ).toBe(false);
});
it("includes points on both sides of a dateline view", () => {
  const o = item("point");
  expect(
    inViewport(
      { ...o, position: { latitude: 0, longitude: 179 } } as Observation,
      { west: 170, east: -170, south: -5, north: 5 },
    ),
  ).toBe(true);
  expect(
    inViewport(
      { ...o, position: { latitude: 0, longitude: 0 } } as Observation,
      { west: 170, east: -170, south: -5, north: 5 },
    ),
  ).toBe(false);
});
