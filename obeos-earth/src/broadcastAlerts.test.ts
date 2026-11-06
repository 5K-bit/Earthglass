import { describe, expect, it } from "vitest";
import {
  activeAlerts, alertFeedFresh, alertPolygons, assessAlertBanner, assessRadar, parseAlertFeed, parseAlerts,
  MAX_FEED_AGE_MS, type AlertFeature, type RadarMeta,
} from "./broadcastAlerts";

const NOW = Date.parse("2026-11-04T18:50:00Z");
const radar: RadarMeta = { observed_at: "2026-11-04T18:46:12Z", bbox: [-125, 24, -66, 50], image: "/weather/radar/latest.png", coverage: "CONUS only" };
const poly = { type: "Polygon", coordinates: [[[-74.2, 40.6], [-73.8, 40.6], [-73.8, 40.9], [-74.2, 40.9], [-74.2, 40.6]]] };
const alert = (id: string, severity: string, ends: string | null, geometry: AlertFeature["geometry"] = null, event = "Flood Warning"): AlertFeature =>
  ({ id, geometry, properties: { event, severity, ends, expires: null, area_desc: "Bronx, NY" } });

describe("radar safety", () => {
  it("shows live radar only when observed recently and the feed is fresh", () => {
    expect(assessRadar(radar, NOW, NOW - 1000).state).toBe("live");
  });
  it("never shows data when radar is unavailable", () => {
    const a = assessRadar(null, NOW, null);
    expect(a.state).toBe("unavailable");
    expect(a.image).toBeNull();
  });
  it("marks old observations, stale feeds and degraded services stale", () => {
    expect(assessRadar({ ...radar, observed_at: "2026-11-04T18:20:00Z" }, NOW, NOW).state).toBe("stale");
    expect(assessRadar(radar, NOW, NOW - MAX_FEED_AGE_MS - 1).state).toBe("stale");
    expect(assessRadar(radar, NOW, null).state).toBe("stale");
    expect(assessRadar({ ...radar, status: "degraded" }, NOW, NOW).state).toBe("stale");
    expect(assessRadar({ ...radar, stale: true }, NOW, NOW).state).toBe("stale");
  });
  it("withholds the image and map rectangle of every non-live frame so the globe draws nothing", () => {
    for (const a of [
      assessRadar({ ...radar, observed_at: "2026-11-04T18:20:00Z" }, NOW, NOW),
      assessRadar(radar, NOW, NOW - MAX_FEED_AGE_MS - 1),
      assessRadar({ ...radar, status: "degraded" }, NOW, NOW),
      assessRadar({ ...radar, stale: true }, NOW, NOW),
      assessRadar(null, NOW, null),
    ]) {
      expect(a.image).toBeNull();
      expect(a.rectangle).toBeNull();
    }
    expect(assessRadar({ ...radar, stale: true }, NOW, NOW).observedAt).toBe(radar.observed_at);
    expect(assessRadar(radar, NOW, NOW).image).toBe("/weather/radar/latest.png");
  });
  it("rejects untrusted image paths, bad boxes and future timestamps", () => {
    expect(assessRadar({ ...radar, image: "https://evil.example/r.png" }, NOW, NOW).state).toBe("unavailable");
    expect(assessRadar({ ...radar, bbox: [10, 0, -10, 5] }, NOW, NOW).state).toBe("unavailable");
    expect(assessRadar({ ...radar, observed_at: "2026-11-05T18:46:12Z" }, NOW, NOW).state).toBe("unavailable");
  });
});

describe("alert banner safety", () => {
  const fresh = (features: AlertFeature[]) => ({ features, lastFetchMs: NOW - 1000, ok: true, retrievedMs: NOW - 30_000, serverStale: false });
  it("never says 'no alerts' when the feed is down or old", () => {
    expect(assessAlertBanner({ features: [], lastFetchMs: null, ok: false }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(assessAlertBanner({ features: [], lastFetchMs: NOW - MAX_FEED_AGE_MS - 1, ok: true }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(assessAlertBanner(fresh([]), "NEW YORK", NOW).state).toBe("clear");
  });
  it("a successful HTTP reply carrying stale or unverifiable data never produces 'no alerts'", () => {
    const base = fresh([]);
    expect(assessAlertBanner({ ...base, serverStale: true }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(assessAlertBanner({ ...base, retrievedMs: NOW - 6 * 60_000 }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(assessAlertBanner({ ...base, retrievedMs: null }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(assessAlertBanner({ features: [], lastFetchMs: NOW - 1000, ok: true }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(alertFeedFresh(base, NOW)).toBe(true);
  });
  it("a future-dated feed (clock mismatch) never produces 'no alerts'", () => {
    const base = fresh([]);
    expect(assessAlertBanner({ ...base, retrievedMs: NOW + 60 * 60_000 }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(assessAlertBanner({ ...base, lastFetchMs: NOW + 60 * 60_000 }, "NEW YORK", NOW).state).toBe("unavailable");
    expect(assessAlertBanner({ ...base, retrievedMs: NOW + 60_000 }, "NEW YORK", NOW).state).toBe("clear");
  });
  it("reads freshness from the server's cache metadata", () => {
    const body = (stale: unknown, retrieved: string | undefined) => ({
      type: "FeatureCollection", features: [],
      metadata: { cache: stale === undefined ? undefined : { status: "cache", stale }, source: retrieved ? { retrieved_at: retrieved } : {} },
    });
    expect(parseAlertFeed(body(false, "2026-11-04T18:49:30Z"))).toMatchObject({ serverStale: false, retrievedMs: Date.parse("2026-11-04T18:49:30Z") });
    expect(parseAlertFeed(body(true, "2026-11-04T18:49:30Z")).serverStale).toBe(true);
    expect(parseAlertFeed(body(undefined, undefined))).toMatchObject({ serverStale: true, retrievedMs: null });
    expect(parseAlertFeed({ type: "FeatureCollection", features: [] }).serverStale).toBe(true);
  });
  it("leads with the most severe alert and counts the rest", () => {
    const banner = assessAlertBanner(fresh([
      alert("a", "Minor", "2026-11-04T23:00:00Z", null, "Small Craft Advisory"),
      alert("b", "Extreme", "2026-11-04T20:00:00Z", null, "Tornado Warning"),
    ]), "NEW YORK", NOW);
    expect(banner).toMatchObject({ state: "alert", headline: "TORNADO WARNING", count: 2, severity: "Extreme" });
    expect(banner.detail).toContain("UNTIL 20:00 UTC");
  });
  it("drops alerts past their end time even if the feed is stale", () => {
    expect(activeAlerts([alert("a", "Severe", "2026-11-04T18:00:00Z")], NOW)).toHaveLength(0);
  });
  it("rejects malformed payloads", () => {
    expect(() => parseAlerts({ error: "x" })).toThrow();
    expect(parseAlerts({ features: [alert("a", "Minor", null), { nope: 1 }] })).toHaveLength(1);
  });
});

describe("alert polygons", () => {
  it("flattens polygons and multipolygons, skipping zone-only alerts", () => {
    const multi = { type: "MultiPolygon", coordinates: [poly.coordinates, poly.coordinates] };
    const out = alertPolygons([alert("a", "Severe", null, poly), alert("b", "Severe", null, multi), alert("c", "Severe", null, null)], NOW);
    expect(out.map(p => p.id)).toEqual(["a#0", "b#0", "b#1"]);
    expect(out[0].positions).toHaveLength(10);
  });
  it("skips expired alerts and bad coordinates", () => {
    const bad = { type: "Polygon", coordinates: [[["x", 1], [2, 3]]] };
    expect(alertPolygons([alert("a", "Severe", "2026-11-04T18:00:00Z", poly), alert("b", "Severe", null, bad)], NOW)).toHaveLength(0);
  });
});
