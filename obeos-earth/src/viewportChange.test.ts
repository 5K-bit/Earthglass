import { it, expect } from "vitest";
import { viewportSignature } from "./viewportChange";
it("ignores floating point camera drift but retains actual pans and zooms", () => {
  const viewport = {
    west: -75.04305,
    south: 40.26861,
    east: -72.96889,
    north: 41.15047,
  };
  const camera = {
    latitude: 40.71427,
    longitude: -74.00597,
    altitude_m: 150000,
  };
  const first = viewportSignature(viewport, camera);
  expect(
    viewportSignature(
      { ...viewport, west: viewport.west + 1e-10 },
      { ...camera, altitude_m: 150000.000001 },
    ),
  ).toBe(first);
  expect(
    viewportSignature({ ...viewport, west: viewport.west + 0.001 }, camera),
  ).not.toBe(first);
  expect(
    viewportSignature(viewport, { ...camera, altitude_m: 149990 }),
  ).not.toBe(first);
});
