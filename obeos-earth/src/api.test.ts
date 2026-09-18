import { describe, expect, it } from "vitest";
import { normalizeEarthquakeFeed, normalizeEarthquakeFeature } from "./api";

const feature = {
  type: "Feature",
  id: "usgs:test",
  geometry: { type: "Point", coordinates: [-122.1, 37.4, 8.2] },
  properties: {
    magnitude: 3.1,
    title: "M 3.1 - Test",
    place: "Test location",
    observed_at: "2026-09-07T12:00:00Z",
  },
  provenance: {
    source_url: "https://earthquake.usgs.gov/earthquakes/eventpage/test",
  },
};

describe("EarthGlass API normalization", () => {
  it("converts a normalized feature into a renderer model", () => {
    expect(normalizeEarthquakeFeature(feature)).toMatchObject({
      id: "usgs:test",
      longitude: -122.1,
      latitude: 37.4,
      depthKm: 8.2,
      magnitude: 3.1,
    });
  });

  it("preserves provenance and degraded cache state", () => {
    const feed = normalizeEarthquakeFeed({
      type: "FeatureCollection",
      features: [feature],
      metadata: {
        generated_at: "2026-09-07T12:01:00Z",
        source: { attribution: "U.S. Geological Survey (USGS)" },
        cache: { status: "cache", stale: true },
      },
    });
    expect(feed.earthquakes).toHaveLength(1);
    expect(feed.cacheStatus).toBe("cache");
    expect(feed.stale).toBe(true);
  });

  it("rejects out-of-range coordinates", () => {
    expect(() =>
      normalizeEarthquakeFeature({
        ...feature,
        geometry: { type: "Point", coordinates: [200, 37.4] },
      }),
    ).toThrow("coordinates are invalid");
  });
});
