export type Earthquake = {
  id: string;
  longitude: number;
  latitude: number;
  depthKm: number | null;
  magnitude: number | null;
  title: string;
  place: string;
  observedAt: string;
  sourceUrl: string;
};

export type EarthquakeFeed = {
  earthquakes: Earthquake[];
  generatedAt: string;
  attribution: string;
  cacheStatus: "live" | "cache";
  stale: boolean;
};

type JsonObject = Record<string, unknown>;

const API_BASE = (
  import.meta.env.VITE_EARTHGLASS_API_BASE ?? "http://127.0.0.1:8000/api"
).replace(/\/$/, "");

function object(value: unknown, name: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${name} must be an object`);
  }
  return value as JsonObject;
}

function text(value: unknown, fallback = "Unknown"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function normalizeEarthquakeFeature(value: unknown): Earthquake {
  const feature = object(value, "feature");
  const geometry = object(feature.geometry, "feature.geometry");
  const properties = object(feature.properties, "feature.properties");
  const provenance = object(feature.provenance, "feature.provenance");
  const coordinates = geometry.coordinates;

  if (geometry.type !== "Point" || !Array.isArray(coordinates)) {
    throw new Error("EarthGlass earthquake geometry must be a Point");
  }
  const longitude = coordinates[0];
  const latitude = coordinates[1];
  if (
    typeof longitude !== "number" ||
    typeof latitude !== "number" ||
    !Number.isFinite(longitude) ||
    !Number.isFinite(latitude) ||
    longitude < -180 ||
    longitude > 180 ||
    latitude < -90 ||
    latitude > 90
  ) {
    throw new Error("EarthGlass earthquake coordinates are invalid");
  }

  return {
    id: text(feature.id, "unknown-earthquake"),
    longitude,
    latitude,
    depthKm: optionalNumber(coordinates[2]),
    magnitude: optionalNumber(properties.magnitude),
    title: text(properties.title, "Earthquake"),
    place: text(properties.place),
    observedAt: text(properties.observed_at, "Unknown time"),
    sourceUrl: text(provenance.source_url, "https://earthquake.usgs.gov/"),
  };
}

export function normalizeEarthquakeFeed(value: unknown): EarthquakeFeed {
  const collection = object(value, "EarthGlass response");
  const metadata = object(collection.metadata, "EarthGlass metadata");
  const source = object(metadata.source, "EarthGlass source metadata");
  const cache = object(metadata.cache, "EarthGlass cache metadata");

  if (
    collection.type !== "FeatureCollection" ||
    !Array.isArray(collection.features)
  ) {
    throw new Error("EarthGlass response must be a FeatureCollection");
  }
  if (cache.status !== "live" && cache.status !== "cache") {
    throw new Error("EarthGlass cache status is invalid");
  }

  return {
    earthquakes: collection.features.map(normalizeEarthquakeFeature),
    generatedAt: text(metadata.generated_at, "Unknown time"),
    attribution: text(source.attribution, "U.S. Geological Survey (USGS)"),
    cacheStatus: cache.status,
    stale: cache.stale === true,
  };
}

async function requestFeed(method: "GET" | "POST", signal?: AbortSignal) {
  const suffix = method === "POST" ? "/refresh" : "/features";
  const response = await fetch(`${API_BASE}/layers/earthquakes${suffix}`, {
    method,
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    const detail =
      typeof errorBody.detail === "string"
        ? errorBody.detail
        : response.statusText;
    throw new Error(`EarthGlass ${response.status}: ${detail}`);
  }
  return normalizeEarthquakeFeed(await response.json());
}

export function getEarthquakes(signal?: AbortSignal): Promise<EarthquakeFeed> {
  return requestFeed("GET", signal);
}

export function refreshEarthquakes(): Promise<EarthquakeFeed> {
  return requestFeed("POST");
}
