import type { Observation, ProviderHealth, Viewport } from "./contracts";
import type { EarthArguments } from "./earthControl.generated";

export type Annotation = {
  annotation_id: string;
  label: string;
  geometry: "point" | "line" | "polygon";
  coordinates: number[][];
  color: string;
};
export type SceneState = {
  schema_version: string;
  scene_id: string;
  revision: number;
  enabled_layers?: string[];
  basemap?: import("./mapChoice").Basemap;
  network_mode?: "auto" | "offline";
  imagery?: { product: string; opacity: number }[];
  camera_revision?: number;
  camera: {
    mode: string;
    latitude?: number;
    longitude?: number;
    altitude_m?: number;
    entity_id?: string;
    distance_m?: number;
  };
  view?: { latitude: number; longitude: number; altitude_m: number };
  active_investigation_id?: string;
  selected_entity_id: string | null;
  tracked_entity_id: string | null;
  annotations: Annotation[];
  timeline: { at: string | null; playing: boolean; speed: number };
};
export type Provider = {
  id: string;
  layer: string;
  label: string;
  enabled: boolean;
  coverage: string;
  attribution: string;
  local?: boolean;
  credential?: string | null;
  health: ProviderHealth;
};
export type ControlResult = {
  schema_version: string;
  request_id: string;
  scene_id: string;
  ok: boolean;
  result: unknown;
  scene?: SceneState;
  error: { code: string; message: string } | null;
};
export type ObservationPage = {
  observations: Observation[];
  volatile_observations?: Observation[];
  sequence: number;
  snapshot_rowid?: number;
  next_cursor: number | null;
};
type Bridge = {
  command(raw: string): void;
  result: { connect(callback: (raw: string) => void): void };
};
declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: new (
      transport: unknown,
      callback: (channel: { objects: { earthBridge: Bridge } }) => void,
    ) => unknown;
    earthMetrics?: Record<string, unknown>;
  }
}
let bridgePromise: Promise<Bridge | null> | undefined;
const pending = new Map<string, (result: ControlResult) => void>();
function nativeBridge(): Promise<Bridge | null> {
  if (!window.qt) return Promise.resolve(null);
  if (!bridgePromise)
    bridgePromise = new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = "qrc:///qtwebchannel/qwebchannel.js";
      script.onerror = () => resolve(null);
      script.onload = () => {
        if (!window.QWebChannel || !window.qt) return resolve(null);
        new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
          const bridge = channel.objects.earthBridge;
          bridge.result.connect((raw) => {
            const result = JSON.parse(raw) as ControlResult;
            pending.get(result.request_id)?.(result);
          });
          resolve(bridge);
        });
      };
      document.head.appendChild(script);
    });
  return bridgePromise;
}
let sessionPromise: Promise<void> | undefined;
async function ensureSession() {
  if (typeof window === "undefined") return;
  if (!sessionPromise)
    sessionPromise = (async () => {
      const ticket = new URLSearchParams(window.location.hash.slice(1)).get(
        "connect",
      );
      if (!ticket) return;
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
      const result = await fetch("/api/session", {
        method: "POST",
        headers: { Authorization: "Bearer " + ticket },
      });
      if (!result.ok)
        throw new Error(
          "Browser session expired. Open Earth from the native workspace again.",
        );
    })();
  return sessionPromise;
}
let privateViewerToken: string | null = null;
export function setPrivateViewerToken(value: string | null) {
  privateViewerToken = value;
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  await ensureSession();
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
      ...(privateViewerToken &&
      (path === "/private/v2/presence" ||
        path.startsWith("/private/v2/presence/") ||
        path.startsWith("/private/v2/presence?"))
        ? { Authorization: "Bearer " + privateViewerToken }
        : {}),
    },
    signal: options.signal ?? AbortSignal.timeout(15000),
  });
  if (!response.ok)
    throw new Error(`Local service returned ${response.status}`);
  return response.json() as Promise<T>;
}
export async function command<K extends keyof EarthArguments>(
  name: K,
  args: EarthArguments[K] = {} as EarthArguments[K],
  sceneId = "home",
  daise = false,
): Promise<ControlResult> {
  const payload = {
    schema_version: "1.0",
    request_id: crypto.randomUUID(),
    scene_id: sceneId,
    command: name,
    arguments: args,
  };
  const bridge = daise ? null : await nativeBridge();
  const result = bridge
    ? await new Promise<ControlResult>((resolve, reject) => {
        const timeout = setTimeout(() => {
          pending.delete(payload.request_id);
          reject(new Error("Earth command timed out"));
        }, 15000);
        pending.set(payload.request_id, (value) => {
          clearTimeout(timeout);
          pending.delete(payload.request_id);
          resolve(value);
        });
        bridge.command(JSON.stringify(payload));
      })
    : await request<ControlResult>(
        daise ? "/api/daise/control" : "/api/control",
        { method: "POST", body: JSON.stringify(payload) },
      );
  if (!result.ok)
    throw new Error(result.error?.message ?? "Earth command failed");
  return result;
}
export function observationQuery(
  viewport?: Viewport,
  at?: string | null,
  cursor = 0,
  snapshotRowid?: number,
) {
  const params = new URLSearchParams({ limit: "2000", cursor: String(cursor) });
  if (viewport)
    Object.entries(viewport).forEach(([key, value]) =>
      params.set(key, String(value)),
    );
  if (at) params.set("at", at);
  if (snapshotRowid !== undefined)
    params.set("snapshot_rowid", String(snapshotRowid));
  return "/api/v2/observations?" + params;
}
export function isNewer(next: Observation, previous?: Observation) {
  return (
    !previous ||
    Date.parse(next.observed_at) >= Date.parse(previous.observed_at)
  );
}
