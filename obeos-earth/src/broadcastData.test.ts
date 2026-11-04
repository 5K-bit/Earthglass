import { describe, expect, it } from "vitest";
import { assessCatalog, assessLayer, overlayUrl, MAX_FEED_AGE_MS, type WeatherLayer } from "./broadcastData";

const NOW = Date.parse("2026-11-04T12:00:00Z");
const layer: WeatherLayer = {
  id: "temperature", name: "Temperature", unit: "C",
  metadata: {
    cycle: "2026-11-04T06:00:00Z",
    generatedAt: "2026-11-04T06:20:00Z",
    forecastHour: 0,
    assets: { image: "/weather/gfs/latest/temperature.png" },
    provenance: { dataKind: "model_analysis", model: "NOAA GFS" },
  },
};

describe("broadcast weather safety", () => {
  it("never represents missing data as current weather", () => {
    expect(assessLayer(undefined, NOW).state).toBe("demo");
  });
  it("recognizes an appropriately timestamped f000 analysis", () => {
    expect(assessLayer(layer, NOW, NOW - 1000).state).toBe("model");
  });
  it("marks old cycles stale regardless of generation timestamp", () => {
    const old = { ...layer, metadata: { ...layer.metadata!, cycle: "2026-11-03T18:00:00Z" } };
    expect(assessLayer(old, NOW).state).toBe("stale");
  });
  it("does not label offline or degraded retained products as current", () => {
    expect(assessLayer({ ...layer, offline: true }, NOW).state).toBe("stale");
    const degraded = { ...layer, metadata: { ...layer.metadata!, status: "stale" } };
    expect(assessLayer(degraded, NOW).state).toBe("stale");
  });
  it("rejects untrusted asset paths", () => {
    const unsafe = { ...layer, metadata: { ...layer.metadata!, assets: { image: "https://example.com/weather.png" } } };
    expect(assessLayer(unsafe, NOW).state).toBe("unsupported");
  });
  it("rejects future timestamps and non-analysis products", () => {
    const future = { ...layer, metadata: { ...layer.metadata!, cycle: "2026-11-05T06:00:00Z" } };
    const forecast = { ...layer, metadata: { ...layer.metadata!, provenance: { dataKind: "model_forecast" } } };
    expect(assessLayer(future, NOW).state).toBe("stale");
    expect(assessLayer(forecast, NOW).state).toBe("unsupported");
  });
  it("marks retained data stale when the feed stops refreshing", () => {
    expect(assessLayer(layer, NOW, NOW - MAX_FEED_AGE_MS - 1).state).toBe("stale");
    expect(assessLayer(layer, NOW, null).state).toBe("stale");
  });
  it("cache-busts overlay URLs by model cycle", () => {
    const a = assessLayer(layer, NOW, NOW);
    expect(overlayUrl("", a)).toBe("/weather/gfs/latest/temperature.png?cycle=2026-11-04T06%3A00%3A00Z");
    expect(overlayUrl("", assessLayer(undefined, NOW))).toBeNull();
  });
  it("rejects malformed catalog bodies", () => {
    expect(() => assessCatalog({ error: "offline" })).toThrow();
    expect(assessCatalog([layer, { foo: "bar" }])).toHaveLength(1);
  });
});
