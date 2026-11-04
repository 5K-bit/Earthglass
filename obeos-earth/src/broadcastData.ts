/** Broadcast boundary: weather model analysis is not observed radar or a forecast. */
export type WeatherLayer = {
  id: string;
  name: string;
  unit: string;
  offline?: boolean;
  metadata?: {
    cycle: string;
    generatedAt?: string;
    status?: string;
    forecastHour?: number;
    assets: { image: string };
    provenance?: { dataKind?: string; model?: string };
  } | null;
};

export type LayerAssessment = {
  state: "demo" | "model" | "stale" | "unsupported";
  description: string;
  cycle: string | null;
  asset: string | null;
};

const SAFE_IMAGE = /^\/weather\/gfs\/latest\/[a-zA-Z0-9_-]+\.png$/;
const MAX_CYCLE_AGE_MS = 10 * 60 * 60 * 1000;
/** If the catalog has not been refreshed this recently, retained data must not look current. */
export const MAX_FEED_AGE_MS = 3 * 60 * 1000;

export function assessLayer(
  layer: WeatherLayer | undefined,
  nowMs = Date.now(),
  lastFetchMs: number | null = null,
): LayerAssessment {
  const metadata = layer?.metadata;
  if (!metadata) {
    return { state: "demo", description: "Illustrative data only · not a real forecast", cycle: null, asset: null };
  }
  if (!SAFE_IMAGE.test(metadata.assets?.image ?? "") ||
      metadata.provenance?.dataKind !== "model_analysis" ||
      metadata.forecastHour !== 0) {
    return { state: "unsupported", description: "Unsupported or unverified weather product", cycle: metadata.cycle ?? null, asset: null };
  }
  const cycleMs = Date.parse(metadata.cycle);
  const generatedMs = Date.parse(metadata.generatedAt ?? "");
  if (!Number.isFinite(cycleMs) || !Number.isFinite(generatedMs)) {
    return { state: "unsupported", description: "Missing trustworthy model timestamps", cycle: null, asset: null };
  }
  const feedStale = lastFetchMs === null || nowMs - lastFetchMs > MAX_FEED_AGE_MS;
  if (feedStale || layer?.offline || ["stale", "error", "missing"].includes(metadata.status ?? "") ||
      cycleMs > nowMs + 60 * 60 * 1000 || generatedMs > nowMs + 60 * 60 * 1000 ||
      nowMs - cycleMs > MAX_CYCLE_AGE_MS) {
    return { state: "stale", description: "Old or inconsistent model cycle · not for air", cycle: metadata.cycle, asset: metadata.assets.image };
  }
  return { state: "model", description: "NOAA GFS model analysis · editorial review required", cycle: metadata.cycle, asset: metadata.assets.image };
}

export function assessCatalog(value: unknown): WeatherLayer[] {
  if (!Array.isArray(value)) throw new Error("Weather catalog is not an array");
  return value.filter((item): item is WeatherLayer => Boolean(item &&
    typeof item === "object" && typeof item.id === "string" &&
    typeof item.name === "string" && typeof item.unit === "string"));
}

/** Cache-busted overlay URL so a new model cycle is never served from a cached copy. */
export function overlayUrl(origin: string, assessment: LayerAssessment): string | null {
  if (!assessment.asset) return null;
  const cycle = assessment.cycle ? "?cycle=" + encodeURIComponent(assessment.cycle) : "";
  return origin + assessment.asset + cycle;
}
