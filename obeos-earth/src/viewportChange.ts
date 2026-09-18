import type { Viewport } from "./contracts";
export function viewportSignature(
  viewport: Viewport,
  camera: { latitude: number; longitude: number; altitude_m: number },
) {
  return (
    [
      viewport.west,
      viewport.south,
      viewport.east,
      viewport.north,
      camera.latitude,
      camera.longitude,
    ]
      .map((v) => v.toFixed(4))
      .join(",") +
    "," +
    Math.round(camera.altitude_m)
  );
}
