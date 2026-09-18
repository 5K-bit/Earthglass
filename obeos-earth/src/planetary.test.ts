import { describe, it, expect, vi, beforeEach } from "vitest";
const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  providers: [] as { url: string; credit: unknown }[],
}));
vi.mock("./controlApi", () => ({ request: mocks.request }));
vi.mock("cesium", () => ({
  Credit: class {
    constructor(public text: string) {}
  },
  UrlTemplateImageryProvider: class {
    errorEvent = { addEventListener: () => () => {} };
    constructor(options: { url: string; credit: unknown }) {
      mocks.providers.push(options);
    }
  },
}));
import { ImageryController } from "./imageryController";
import {
  observationIsStale,
  observationVisibleAt,
} from "./observationFreshness";
import type { Observation } from "./contracts";
const product = {
  id: "true_color",
  label: "True color",
  available: true,
  maximum_level: 8,
  default_time: "2026-09-11",
  attribution: "NASA",
  provider: "NASA",
};
function viewer() {
  return {
    imageryLayers: {
      addImageryProvider: vi.fn(() => ({ alpha: 1 })),
      remove: vi.fn(),
    },
    scene: { requestRender: vi.fn() },
  };
}
beforeEach(() => {
  mocks.request.mockReset();
  mocks.providers.length = 0;
});
describe("imagery timeline", () => {
  it("uses the resolved source frame rather than the requested date", async () => {
    mocks.request.mockResolvedValue({ time: "2026-09-09" });
    const v = viewer(),
      controller = new ImageryController(v as never, vi.fn());
    controller.apply(
      [product],
      [{ product: "true_color", opacity: 0.5 }],
      "2026-09-10T12:00:00Z",
    );
    await Promise.resolve();
    await Promise.resolve();
    expect(mocks.providers[0].url).toContain("/2026-09-09/");
    expect(mocks.providers[0].credit).toHaveProperty(
      "text",
      "NASA · 2026-09-09",
    );
    controller.destroy();
  });
  it("suppresses a late frame after the layer was disabled", async () => {
    let finish: (value: { time: string }) => void = () => {};
    mocks.request.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const v = viewer(),
      controller = new ImageryController(v as never, vi.fn());
    controller.apply(
      [product],
      [{ product: "true_color", opacity: 0.5 }],
      null,
    );
    controller.apply([product], [], null);
    finish({ time: "2026-09-11" });
    await Promise.resolve();
    await Promise.resolve();
    expect(v.imageryLayers.addImageryProvider).not.toHaveBeenCalled();
    controller.destroy();
  });
  it("removes an old frame when the requested historical date is unavailable", async () => {
    const v = viewer(),
      report = vi.fn(),
      controller = new ImageryController(v as never, report);
    mocks.request.mockResolvedValueOnce({ time: "2026-09-11" });
    controller.apply(
      [product],
      [{ product: "true_color", opacity: 0.5 }],
      null,
    );
    await Promise.resolve();
    await Promise.resolve();
    mocks.request.mockRejectedValueOnce(new Error("No frame"));
    controller.apply(
      [product],
      [{ product: "true_color", opacity: 0.5 }],
      "2000-01-01T00:00:00Z",
    );
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(v.imageryLayers.remove).toHaveBeenCalled();
    expect(report).toHaveBeenCalled();
    controller.destroy();
  });
});
it("uses vehicle fix age and hides expired alerts at the selected time", () => {
  const at = Date.parse("2026-09-11T12:00:00Z");
  const bus = {
    layer: "transit_vehicles",
    observed_at: new Date(at - 61000).toISOString(),
    received_at: new Date(at).toISOString(),
    properties: {},
  } as Observation;
  expect(observationIsStale(bus, at)).toBe(true);
  const alert = {
    ...bus,
    layer: "weather_alerts",
    properties: { expires: "2026-09-11T11:00:00Z" },
  };
  expect(observationVisibleAt(alert, at)).toBe(false);
  expect(observationVisibleAt(alert, at - 7200000)).toBe(true);
});
