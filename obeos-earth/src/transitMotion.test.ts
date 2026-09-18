import { it, expect } from "vitest";
import { canInterpolateTransit } from "./transitMotion";
import type { Observation } from "./contracts";
it("interpolates recent transit fixes but never stale, duplicate, backwards or future fixes", () => {
  const now = Date.parse("2026-09-11T12:00:00Z");
  const fix = (age: number) =>
    ({
      entity_id: "mta:1",
      layer: "transit_vehicles",
      observed_at: new Date(now - age).toISOString(),
    }) as Observation;
  expect(canInterpolateTransit(fix(30000), fix(1000), now)).toBe(true);
  for (const [a, b] of [
    [30000, 30000],
    [1000, 30000],
    [130000, 61000],
    [1000, -20000],
    [200000, 1000],
  ]) {
    expect(canInterpolateTransit(fix(a), fix(b), now)).toBe(false);
  }
  expect(canInterpolateTransit(undefined, fix(0), now)).toBe(false);
});
