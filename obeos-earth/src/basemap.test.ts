import { describe, it, expect, vi } from "vitest";
import { resolveBasemap } from "./mapChoice";
import { BasemapController } from "./basemap";
vi.mock("cesium", () => ({
  TileMapServiceImageryProvider: { fromUrl: async () => ({}) },
  Credit: class {},
  UrlTemplateImageryProvider: class {
    errorEvent = event();
    url: string;
    constructor(options: { url: string }) {
      this.url = options.url;
    }
  },
}));
function event() {
  const listeners = new Set<(...args: unknown[]) => void>();
  return {
    addEventListener: (fn: (...args: unknown[]) => void) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    emit: (...args: unknown[]) => {
      for (const fn of listeners) fn(...args);
    },
    listeners,
  };
}
function scene() {
  const layers: {
    provider: { errorEvent: ReturnType<typeof event> };
    show: boolean;
  }[] = [];
  return {
    isDestroyed: () => false,
    imageryLayers: {
      addImageryProvider: (
        provider: (typeof layers)[number]["provider"],
        index?: number,
      ) => {
        const layer = { provider, show: true };
        layers.splice(index ?? layers.length, 0, layer);
        return layer;
      },
      remove: (layer: (typeof layers)[number]) =>
        layers.splice(layers.indexOf(layer), 1),
    },
    scene: {
      requestRender: vi.fn(),
      globe: { tileLoadProgressEvent: event() },
    },
    layers,
  };
}
describe("basemap zoom and recovery", () => {
  it("uses detailed imagery online while enforcing explicit offline mode", () => {
    expect(resolveBasemap("auto", false)).toBe("satellite");
    expect(resolveBasemap("streets", false)).toBe("streets");
    expect(resolveBasemap("satellite", true)).toBe("offline");
  });
  it("retains a local overview, reports failed tiles, and permits a clean retry", async () => {
    const viewer = scene(),
      status = vi.fn();
    const map = new BasemapController(viewer as never, status);
    await map.set("satellite");
    expect(viewer.layers).toHaveLength(3);
    for (let n = 0; n < 3; n++) viewer.layers[1].provider.errorEvent.emit();
    expect(viewer.layers[0].show).toBe(true);
    expect(viewer.layers[1].show).toBe(false);
    expect(viewer.layers[2].show).toBe(false);
    expect(status.mock.lastCall?.[0].state).toBe("fallback");
    await map.set("streets");
    viewer.scene.globe.tileLoadProgressEvent.emit(0);
    expect(status.mock.lastCall?.[0].state).toBe("ready");
    expect(viewer.layers).toHaveLength(2);
    map.destroy();
    expect(viewer.scene.globe.tileLoadProgressEvent.listeners.size).toBe(0);
  });
  it("labels satellite imagery and leaves street tiles to their own cartography", async () => {
    const viewer = scene(),
      map = new BasemapController(viewer as never, vi.fn());
    const urls = () =>
      viewer.layers.map(
        (l) => (l.provider as unknown as { url?: string }).url ?? "",
      );
    await map.set("satellite");
    expect(
      urls().filter((u) => u.includes("World_Boundaries_and_Places")),
    ).toHaveLength(1);
    await map.set("streets");
    expect(viewer.layers).toHaveLength(2);
    expect(
      urls().filter((u) => u.includes("World_Boundaries_and_Places")),
    ).toHaveLength(0);
    map.destroy();
  });
  it("does not create remote imagery for offline startup", async () => {
    const viewer = scene(),
      map = new BasemapController(viewer as never, vi.fn());
    await map.set("offline");
    expect(viewer.layers).toHaveLength(1);
    map.destroy();
  });
});

it("retries public tiles after an outage and cancels recovery in offline mode", async () => {
  vi.useFakeTimers();
  const viewer = scene(),
    map = new BasemapController(viewer as never, vi.fn());
  try {
    await map.set("satellite");
    const failed = viewer.layers[1];
    for (let n = 0; n < 3; n++) failed.provider.errorEvent.emit();
    await vi.advanceTimersByTimeAsync(60000);
    expect(viewer.layers[1]).not.toBe(failed);
    for (let n = 0; n < 3; n++) viewer.layers[1].provider.errorEvent.emit();
    await map.set("offline");
    await vi.advanceTimersByTimeAsync(90000);
    expect(viewer.layers).toHaveLength(1);
  } finally {
    map.destroy();
    vi.useRealTimers();
  }
});
