/** Broadcast boundary for observed radar and NWS alerts. Pure functions: no rendering, no I/O. */

export const MAX_FEED_AGE_MS = 3 * 60 * 1000;
export const MAX_RADAR_OBSERVATION_AGE_MS = 15 * 60 * 1000;

export type RadarMeta = {
  observed_at: string;
  stale?: boolean;
  status?: string;
  bbox: number[];
  image: string;
  coverage?: string;
};

export type RadarAssessment = {
  state: "live" | "stale" | "unavailable";
  description: string;
  observedAt: string | null;
  image: string | null;
  rectangle: [number, number, number, number] | null;
};

const SAFE_RADAR_IMAGE = /^\/weather\/radar\/latest\.png$/;

export function assessRadar(meta: RadarMeta | null, nowMs: number, lastFetchMs: number | null): RadarAssessment {
  const none = { observedAt: null, image: null, rectangle: null };
  if (!meta) return { state: "unavailable", description: "RADAR UNAVAILABLE · NO DATA SHOWN", ...none };
  const observedMs = Date.parse(meta.observed_at);
  const [w, s, e, n] = meta.bbox ?? [];
  const validBox = [w, s, e, n].every(v => typeof v === "number" && Number.isFinite(v)) &&
    w >= -180 && e <= 180 && s >= -90 && n <= 90 && w < e && s < n;
  if (!SAFE_RADAR_IMAGE.test(meta.image ?? "") || !Number.isFinite(observedMs) || !validBox ||
      observedMs > nowMs + 5 * 60 * 1000) {
    return { state: "unavailable", description: "RADAR PRODUCT FAILED VALIDATION · NO DATA SHOWN", ...none };
  }
  const base = { observedAt: meta.observed_at, image: meta.image, rectangle: [w, s, e, n] as [number, number, number, number] };
  const feedStale = lastFetchMs === null || nowMs - lastFetchMs > MAX_FEED_AGE_MS;
  if (feedStale || meta.stale || meta.status === "degraded" || nowMs - observedMs > MAX_RADAR_OBSERVATION_AGE_MS) {
    return { state: "stale", description: "RADAR STALE · NOT FOR AIR", ...base };
  }
  return { state: "live", description: "NOAA RADAR · OBSERVED · CONUS ONLY", ...base };
}

export type AlertFeature = {
  id: string;
  geometry: { type: string; coordinates: unknown } | null;
  properties: {
    event?: string | null; headline?: string | null; severity?: string | null;
    expires?: string | null; ends?: string | null; area_desc?: string | null; located?: boolean;
  };
};

export type AlertFeed = { features: AlertFeature[]; lastFetchMs: number | null; ok: boolean };

export function parseAlerts(value: unknown): AlertFeature[] {
  const list = (value as { features?: unknown } | null)?.features;
  if (!Array.isArray(list)) throw new Error("Alert payload is not a FeatureCollection");
  return list.filter((item): item is AlertFeature =>
    Boolean(item && typeof item === "object" && typeof item.id === "string" &&
      item.properties && typeof item.properties === "object"));
}

const SEVERITY_RANK: Record<string, number> = { Extreme: 4, Severe: 3, Moderate: 2, Minor: 1 };
const rank = (a: AlertFeature) => SEVERITY_RANK[a.properties.severity ?? ""] ?? 0;
const endMs = (a: AlertFeature) => Date.parse(a.properties.ends ?? a.properties.expires ?? "");

/** Drops alerts past their end time, so an expired warning disappears even if the feed is stale. */
export function activeAlerts(features: AlertFeature[], nowMs: number): AlertFeature[] {
  return features
    .filter(a => { const end = endMs(a); return !Number.isFinite(end) || end > nowMs; })
    .sort((a, b) => rank(b) - rank(a) || (endMs(a) || Infinity) - (endMs(b) || Infinity));
}

export type AlertBanner = {
  state: "alert" | "clear" | "unavailable";
  headline: string;
  detail: string;
  count: number;
  severity: string | null;
};

export function assessAlertBanner(feed: AlertFeed, city: string, nowMs: number): AlertBanner {
  const feedStale = !feed.ok || feed.lastFetchMs === null || nowMs - feed.lastFetchMs > MAX_FEED_AGE_MS;
  if (feedStale) {
    return { state: "unavailable", headline: "ALERT FEED UNAVAILABLE", detail: "DO NOT RELY ON THIS GRAPHIC FOR ALERT STATUS", count: 0, severity: null };
  }
  const active = activeAlerts(feed.features, nowMs);
  if (active.length === 0) {
    return { state: "clear", headline: "NO ACTIVE NWS ALERTS", detail: city, count: 0, severity: null };
  }
  const top = active[0];
  const until = endMs(top);
  const untilText = Number.isFinite(until)
    ? " · UNTIL " + new Date(until).toLocaleTimeString("en-US", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", hour12: false }) + " UTC"
    : "";
  return {
    state: "alert",
    headline: (top.properties.event ?? "WEATHER ALERT").toUpperCase(),
    detail: (top.properties.area_desc ?? city) + untilText,
    count: active.length,
    severity: top.properties.severity ?? null,
  };
}

export type AlertPolygon = { id: string; severity: string; positions: number[] };

/** Outer rings of Polygon / MultiPolygon alerts as flat [lon, lat, ...] arrays for the globe. */
export function alertPolygons(features: AlertFeature[], nowMs: number, limit = 300): AlertPolygon[] {
  const out: AlertPolygon[] = [];
  for (const alert of activeAlerts(features, nowMs)) {
    const g = alert.geometry;
    if (!g) continue;
    const polygons: unknown[] = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" && Array.isArray(g.coordinates) ? g.coordinates : [];
    polygons.forEach((rings, index) => {
      const outer = Array.isArray(rings) ? rings[0] : null;
      if (!Array.isArray(outer) || outer.length < 4) return;
      const positions = outer.flatMap((p: unknown) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]) ? [p[0] as number, p[1] as number] : []);
      if (positions.length >= 8 && out.length < limit) {
        out.push({ id: alert.id + "#" + index, severity: alert.properties.severity ?? "Unknown", positions });
      }
    });
  }
  return out;
}
