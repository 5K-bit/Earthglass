import { useCallback, useEffect, useRef, useState } from "react";
import type { Observation, Viewport } from "./contracts";
import { command, request, observationQuery } from "./controlApi";
import type {
  Provider,
  SceneState,
  ControlResult,
  ObservationPage,
} from "./controlApi";
import type { SceneController } from "./sceneController";
import { label } from "./observationLabel";
import type { EarthArguments } from "./earthControl.generated";
import { resolveBasemap } from "./mapChoice";
import type { Basemap, MapStatus } from "./mapChoice";
import { PlanetaryPanel, SpaceWeatherPanel } from "./PlanetaryPanel";
import { RasterWeatherPanel } from "./RasterWeatherPanel";
import type { ImageryProduct } from "./imageryController";
import { PresencePanel } from "./PresencePanel";
import { inViewport } from "./visibleDetail";
import { MobilityPanel } from "./MobilityPanel";
import { ObservationDetails } from "./ObservationDetails";
import { restoreSceneContacts } from "./restoreSceneContacts";

type Situation = {
  situation_id: string;
  summary: string;
  freshness_seconds: number;
  uncertainty: string;
  evidence: {
    entity_id: string;
    provider: string;
    observed_at: string;
    source_url: string;
  }[];
  suggestions: string[];
};
type SearchMatch = {
  label: string;
  latitude: number;
  longitude: number;
  entity_id?: string;
};
const groups = [
  {
    title: "Atmosphere",
    layers: [
      "weather",
      "temperature",
      "wind",
      "precipitation",
      "pressure",
      "clouds",
      "weather_alerts",
      "aviation_metar",
      "aviation_taf",
      "aviation_sigmet",
      "aviation_gairmet",
      "aviation_pirep",
    ],
  },
  {
    title: "Orbit and aviation",
    layers: ["aircraft", "satellites", "space_weather", "launches"],
  },
  { title: "Earth events", layers: ["earthquakes", "fires", "natural_events"] },
  {
    title: "Mobility",
    layers: [
      "traffic_speeds",
      "traffic_incidents",
      "transit_vehicles",
      "transit_routes",
      "transit_stops",
      "transit_alerts",
      "bikeshare",
      "cctv",
    ],
  },
  {
    title: "Local context",
    layers: ["traffic", "infrastructure", "perception"],
  },
];
const categories = groups.flatMap((group) => group.layers);
const layerName = (name: string) =>
  name === "cctv"
    ? "Public cameras"
    : name === "traffic"
      ? "Road network"
      : name === "military"
        ? "Military observations"
        : name.charAt(0).toUpperCase() + name.slice(1).replaceAll("_", " ");
const formatTime = (value: string) =>
  new Date(value).toLocaleString(undefined, { hour12: false });
function App() {
  const container = useRef<HTMLDivElement>(null);
  const controller = useRef<SceneController | null>(null);
  const stateRef = useRef<SceneState | null>(null);
  const getController = useCallback(() => controller.current, []);
  const imageryProducts = useRef<ImageryProduct[]>([]);
  const onProducts = useCallback((products: ImageryProduct[]) => {
    imageryProducts.current = products;
    if (stateRef.current)
      controller.current?.setImagery(products, stateRef.current);
  }, []);
  const offlineRef = useRef(false);
  const [offline, setOffline] = useState(false);
  const mapReady = useRef(false);
  const activeMap = useRef<string | null>(null);
  const viewportRef = useRef<Viewport | undefined>(undefined);
  const refreshRef = useRef<() => void>(() => {});
  const [scene, setScene] = useState<SceneState | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("Connecting");
  const [layersOpen, setLayersOpen] = useState(true);
  const [daiseOpen, setDaiseOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const diagnosticsRef = useRef(false);
  diagnosticsRef.current = diagnosticsOpen;
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<Observation | null>(null);
  const [nearby, setNearby] = useState<
    { distance_m: number; observation: Observation }[]
  >([]);
  const [situations, setSituations] = useState<Situation[]>([]);
  const [contacts, setContacts] = useState<Observation[]>([]);
  const [contactCount, setContactCount] = useState(0);
  const [layerCounts, setLayerCounts] = useState<Record<string, number>>({});
  const [diagnostics, setDiagnostics] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState("");
  const [explanation, setExplanation] = useState("");
  const [replay, setReplay] = useState("");
  const [annotationLabel, setAnnotationLabel] = useState("");
  const [annotationGeometry, setAnnotationGeometry] = useState<
    "point" | "line" | "polygon"
  >("point");
  const [annotationCoordinates, setAnnotationCoordinates] = useState("");
  const [watches, setWatches] = useState<
    { name: string; west: number; south: number; east: number; north: number }[]
  >([]);
  const [views, setViews] = useState<
    { id: string; label: string; created: string }[]
  >([]);
  const [map, setMap] = useState<Basemap>("auto");
  const [mapStatus, setMapStatus] = useState<MapStatus | null>(null);
  const syncBasemap = useCallback((preference: Basemap) => {
    if (!mapReady.current || !controller.current) return;
    const mode = resolveBasemap(preference, offlineRef.current);
    if (activeMap.current !== mode) {
      activeMap.current = mode;
      void controller.current.setMap(mode);
    }
  }, []);
  const [flat, setFlat] = useState(false);
  const [cinematic, setCinematic] = useState(true);

  const apply = useCallback(
    (value: SceneState) => {
      const old = stateRef.current;
      if (old && value.revision < old.revision) return;
      stateRef.current = value;
      setScene(value);
      setMap(value.basemap ?? "auto");
      syncBasemap(value.basemap ?? "auto");
      controller.current?.apply(value);
      controller.current?.setImagery(imageryProducts.current, value);
      if (
        old?.timeline.at !== value.timeline.at ||
        old?.active_investigation_id !== value.active_investigation_id
      )
        refreshRef.current();
    },
    [syncBasemap],
  );
  const execute = useCallback(
    async <K extends keyof EarthArguments>(
      name: K,
      args: EarthArguments[K] = {} as EarthArguments[K],
      daise = false,
    ): Promise<ControlResult | null> => {
      try {
        setError("");
        const result = await command(
          name,
          args,
          stateRef.current?.scene_id ?? "home",
          daise,
        );
        if (result.scene) apply(result.scene);
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      }
    },
    [apply],
  );
  const inspect = useCallback(
    async (id: string) => {
      const result = await execute("earth.entity.inspect", { entity_id: id });
      if (result) {
        const value = result.result as Observation;
        setSelected(value);
        const nearbyResult = await execute("earth.entities.nearby", {
          latitude: value.position.latitude,
          longitude: value.position.longitude,
          radius_m: 50000,
          limit: 12,
        });
        // Nearby accepts a geographic center; altitude reference is presentation metadata, not an argument.
        if (nearbyResult) setNearby(nearbyResult.result as typeof nearby);
        request<ObservationPage>(
          "/api/v2/observations?entity_id=" +
            encodeURIComponent(id) +
            "&limit=200",
        )
          .then((page) => controller.current?.setTrails(id, page.observations))
          .catch(() => {});
      }
    },
    [execute],
  );

  useEffect(() => {
    if (!container.current) return;
    let cancelled = false;
    let teardown = () => {};
    void import("./sceneController")
      .then(({ SceneController }) => {
        if (cancelled || !container.current) return;
        let active = true,
          stream: EventSource | null = null,
          abort: AbortController | null = null,
          epoch = 0;
        let viewportTimer: ReturnType<typeof setTimeout> | undefined;
        const sceneController = new SceneController(
          container.current,
          (id) => void inspect(id),
          (viewport, camera) => {
            viewportRef.current = viewport;
            clearTimeout(viewportTimer);
            viewportTimer = setTimeout(() => {
              void request("/api/viewport", {
                method: "POST",
                body: JSON.stringify({ ...viewport, camera }),
              }).catch((e) => setError(String(e)));
              void refresh();
            }, 450);
          },
          setError,
          setMapStatus,
        );
        controller.current = sceneController;
        const updateList = () => {
          setContacts([...sceneController.observations.values()].slice(0, 100));
          setContactCount(sceneController.observations.size);
          const counts: Record<string, number> = {};
          for (const observation of sceneController.observations.values()) {
            const v = viewportRef.current;
            if (v && !inViewport(observation, v)) continue;
            counts[observation.layer] = (counts[observation.layer] ?? 0) + 1;
          }
          setLayerCounts(counts);
        };
        async function refresh() {
          const generation = ++epoch;
          window.earthMetrics = {
            ...window.earthMetrics,
            loadGeneration: generation,
            loadPhase: "query",
            loadedPages: 0,
          };
          abort?.abort();
          abort = new AbortController();
          stream?.close();
          try {
            if (stateRef.current?.active_investigation_id) {
              const saved = await request<{ observations: ObservationPage }>(
                "/api/investigations/" +
                  stateRef.current.active_investigation_id,
                { signal: abort.signal },
              );
              if (!active || generation !== epoch) return;
              sceneController.upsert(saved.observations.observations, true);
              updateList();
              setConnection("Saved investigation · fixed snapshot");
              return;
            }
            const values: Observation[] = [];
            let cursor = 0,
              sequence = 0,
              snapshotRowid: number | undefined;
            for (let pageNumber = 0; pageNumber < 10; pageNumber++) {
              const page = await request<ObservationPage>(
                observationQuery(
                  viewportRef.current,
                  stateRef.current?.timeline.at,
                  cursor,
                  snapshotRowid,
                ),
                { signal: abort.signal },
              );
              if (!active || generation !== epoch) return;
              window.earthMetrics = {
                ...window.earthMetrics,
                loadedPages: pageNumber + 1,
                fetchedTracks: values.length + page.observations.length,
              };
              values.push(
                ...page.observations,
                ...(page.volatile_observations ?? []),
              );
              if (pageNumber === 0) {
                sequence = page.sequence;
                snapshotRowid = page.snapshot_rowid;
              }
              if (page.next_cursor === null) break;
              cursor = page.next_cursor;
            }
            if (
              stateRef.current?.timeline.at &&
              stateRef.current?.enabled_layers?.includes("satellites")
            ) {
              const query = new URLSearchParams({
                at: stateRef.current.timeline.at,
                limit: "2000",
                ...Object.fromEntries(
                  Object.entries(viewportRef.current ?? {}).map(([k, v]) => [
                    k,
                    String(v),
                  ]),
                ),
              });
              const projected = await request<{ data: Observation[] }>(
                "/api/v2/orbits/objects?" + query,
                { signal: abort.signal },
              );
              if (!active || generation !== epoch) return;
              for (let i = values.length - 1; i >= 0; i--)
                if (values[i].layer === "satellites") values.splice(i, 1);
              values.push(...projected.data);
            }
            const restored = await restoreSceneContacts(
              values,
              stateRef.current,
              (path) => request<ObservationPage>(path, { signal: abort!.signal }),
            );
            if (!active || generation !== epoch) return;
            sceneController.upsert(
              restored,
              true,
              !stateRef.current?.timeline.at,
            );
            updateList();
            window.earthMetrics = {
              ...window.earthMetrics,
              loadPhase: "ready",
              loadError: null,
            };
            if (stateRef.current?.selected_entity_id) {
              const observation = sceneController.observations.get(
                stateRef.current.selected_entity_id,
              );
              setSelected(observation ?? null);
            }
            setConnection(
              stateRef.current?.timeline.at
                ? "Replay"
                : offlineRef.current
                  ? "Offline · local workspace"
                  : "Local workspace · public updates enabled",
            );
            if (!stateRef.current?.timeline.at) {
              stream = new EventSource("/api/v2/stream?after=" + sequence);
              stream.addEventListener("observations", (event) => {
                if (generation !== epoch) return;
                const batch = JSON.parse((event as MessageEvent).data) as {
                  changes: {
                    operation: string;
                    entity_id: string;
                    observation: Observation | null;
                  }[];
                };
                const updates: Observation[] = [];
                for (const change of batch.changes) {
                  if (change.operation === "remove")
                    sceneController.remove(change.entity_id);
                  else if (change.observation) updates.push(change.observation);
                }
                sceneController.upsert(updates);
                updateList();
                const selectedId = stateRef.current?.selected_entity_id;
                if (selectedId)
                  setSelected(
                    sceneController.observations.get(selectedId) ?? null,
                  );
                setConnection(
                  offlineRef.current
                    ? "Offline · local workspace"
                    : "Local workspace · public updates enabled",
                );
              });
              stream.addEventListener("resync", () => {
                stream?.close();
                void refresh();
              });
              stream.onerror = () =>
                setConnection("Reconnecting · cached data");
            }
          } catch (e) {
            if (active && generation === epoch && !abort?.signal.aborted) {
              setConnection("Offline · cached data");
              console.warn("Earth scene load:", String(e));
              window.earthMetrics = {
                ...window.earthMetrics,
                loadPhase: "failed",
                loadError: String(e),
              };
              setError(e instanceof Error ? e.message : String(e));
            }
          }
        }
        refreshRef.current = () => void refresh();
        async function catalog() {
          try {
            const result = await request<{
              providers: Provider[];
              offline: boolean;
            }>("/api/v2/catalog");
            if (!active) return;
            offlineRef.current = result.offline;
            setOffline(result.offline);
            mapReady.current = true;
            syncBasemap(stateRef.current?.basemap ?? "auto");
            setProviders(result.providers);
            if (
              !stateRef.current?.active_investigation_id &&
              !stateRef.current?.timeline.at
            )
              setConnection(
                result.offline
                  ? "Offline · local workspace"
                  : "Local workspace · public updates enabled",
              );
            sceneController.setLayers([
              ...new Set(
                result.providers.filter((p) => p.enabled).map((p) => p.layer),
              ),
            ]);
          } catch (e) {
            if (active) {
              setConnection("Offline · cached data");
              console.warn("Earth layer update:", String(e));
              setError(String(e));
            }
          }
        }
        void request<SceneState>("/api/scene")
          .then((value) => {
            if (active) {
              apply(value);
              void refresh();
            }
          })
          .catch((e) => setError(String(e)));
        void catalog();
        const timer = setInterval(() => {
          void catalog();
          if (diagnosticsRef.current) void loadDiagnostics();
          if (window.earthMetrics)
            void request("/api/render-metrics", {
              method: "POST",
              body: JSON.stringify(window.earthMetrics),
            }).catch(() => {});
        }, 5000);
        const periodic = setInterval(() => {
          if (!document.hidden && !stateRef.current?.timeline.playing)
            void refresh();
        }, 30000);
        teardown = () => {
          active = false;
          clearInterval(timer);
          clearInterval(periodic);
          clearTimeout(viewportTimer);
          abort?.abort();
          stream?.close();
          sceneController.destroy();
          controller.current = null;
          mapReady.current = false;
          activeMap.current = null;
        };
      })
      .catch((e) => {
        if (!cancelled)
          setError("Earth renderer could not start: " + String(e));
      });
    return () => {
      cancelled = true;
      teardown();
    };
  }, [apply, inspect, syncBasemap]);

  useEffect(() => {
    if (!scene?.timeline.playing || !scene.timeline.at) return;
    const end = Date.now() + 24 * 60 * 60 * 1000;
    let value = Date.parse(scene.timeline.at),
      inflight = false;
    const timer = setInterval(() => {
      if (inflight) return;
      value = Math.min(end, value + scene.timeline.speed * 1000);
      inflight = true;
      void execute("earth.timeline.set", {
        at: new Date(value).toISOString(),
        advance: true,
      }).finally(() => {
        inflight = false;
        if (value >= end)
          void execute("earth.timeline.play", {
            playing: false,
            speed: scene.timeline.speed,
          });
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [scene?.timeline.playing, scene?.timeline.speed, execute]);

  async function loadDiagnostics() {
    try {
      setDiagnostics({
        service: await request("/api/diagnostics"),
        renderer: window.earthMetrics,
      });
    } catch (e) {
      setError(String(e));
    }
  }
  async function toggleLayer(layer: string, enabled: boolean) {
    const result = await execute(
      enabled ? "earth.layer.disable" : "earth.layer.enable",
      { layer },
    );
    if (result) {
      const values = result.result as Provider[];
      setProviders(values);
      controller.current?.setLayers([
        ...new Set(values.filter((p) => p.enabled).map((p) => p.layer)),
      ]);
      refreshRef.current();
    }
  }
  async function find(event: React.FormEvent) {
    event.preventDefault();
    const result = await execute("earth.search", { query: search });
    setSearched(true);
    if (result)
      setMatches((result.result as { matches: SearchMatch[] }).matches);
  }
  async function describe() {
    setBusy(true);
    const result = await execute("earth.scene.describe", {}, true);
    if (result)
      setSituations((result.result as { situations: Situation[] }).situations);
    setBusy(false);
    setDaiseOpen(true);
  }
  async function explainLocal() {
    setBusy(true);
    try {
      const value = await request<{
        status: string;
        explanation?: string;
        message?: string;
        model?: string;
      }>("/api/daise/explain", {
        method: "POST",
        body: JSON.stringify({
          question:
            question || "Explain this scene and suggest what to investigate.",
        }),
        signal: AbortSignal.timeout(45000),
      });
      setExplanation(
        value.status === "ok"
          ? value.explanation + "\n\nLocal model: " + value.model
          : (value.message ?? "Local explanation is unavailable."),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function snapshot() {
    setBusy(true);
    try {
      const result = await execute("earth.scene.snapshot", {
        label: annotationLabel || "Earth view · " + new Date().toLocaleString(),
      });
      if (result) {
        const id = (result.result as { investigation_id: string })
          .investigation_id;
        const png = await controller.current?.capture();
        if (png)
          await request("/api/investigations/" + id + "/image", {
            method: "POST",
            body: JSON.stringify({ png }),
          });
        setViews(await request("/api/investigations"));
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function restore(id: string) {
    await execute("earth.scene.restore", { investigation_id: id });
  }
  async function annotate() {
    try {
      const coordinates = annotationCoordinates
        ? JSON.parse(annotationCoordinates)
        : selected
          ? [[selected.position.longitude, selected.position.latitude]]
          : null;
      if (!coordinates)
        throw new Error("Select a contact or enter coordinates.");
      await execute("earth.annotation.add", {
        annotation_id: crypto.randomUUID(),
        label: annotationLabel || "Observation",
        geometry: annotationGeometry,
        coordinates,
        color: "gold",
      });
      setAnnotationLabel("");
    } catch (e) {
      setError(String(e));
    }
  }
  const enabledCount = new Set(
    providers.filter((p) => p.enabled).map((p) => p.layer),
  ).size;
  return (
    <main className="earth-shell">
      <div
        className="canvas"
        ref={container}
        aria-label="Interactive Earth canvas"
      />
      <header className="topbar">
        <div className="wordmark">
          <span className="sigil">◈</span>
          <div>
            <strong>
              OBEOS <span>EARTH</span>
            </strong>
            <small>LOCAL SPATIAL WORKSPACE</small>
          </div>
        </div>
        <form className="search" onSubmit={find}>
          <span>⌕</span>
          <input
            aria-label="Search places, coordinates or contacts"
            placeholder="Search a place, contact or coordinates"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="submit">Enter ↵</button>
        </form>
        <button
          className={daiseOpen ? "active" : ""}
          onClick={() => setDaiseOpen(!daiseOpen)}
        >
          D.A.I.S.E. <span className="cyan">✧</span>
        </button>
      </header>
      {(matches.length > 0 || searched) && (
        <div className="search-results panel">
          {!matches.length && (
            <p>
              No city or contact matched. Try a city name or latitude,
              longitude.
            </p>
          )}
          <small>City search: GeoNames · CC BY 4.0 · local index</small>
          {matches.map((m, i) => (
            <button
              key={i}
              onClick={() => {
                void execute("earth.goto", {
                  latitude: m.latitude,
                  longitude: m.longitude,
                  altitude_m: 150000,
                });
                if (m.entity_id) void inspect(m.entity_id);
                setMatches([]);
                setSearched(false);
              }}
            >
              {m.label}
              <small>
                {m.latitude.toFixed(3)}°, {m.longitude.toFixed(3)}°
              </small>
            </button>
          ))}
        </div>
      )}
      <nav className="map-tools" aria-label="Earth navigation">
        <button
          onClick={() => setLayersOpen(!layersOpen)}
          aria-expanded={layersOpen}
        >
          ☷ Layers <span>{enabledCount}</span>
        </button>
        <button onClick={() => void execute("earth.camera.reset")}>
          ⌂ Home
        </button>
        <button
          onClick={() => {
            setFlat(!flat);
            controller.current?.mode(!flat);
          }}
        >
          {flat ? "3D Globe" : "2D Map"}
        </button>
        <select
          aria-label="Network access"
          value={offline ? "offline" : "auto"}
          onChange={async (e) => {
            const result = await execute("earth.network.set", {
              mode: e.target.value as "auto" | "offline",
            });
            if (result?.ok) window.location.reload();
          }}
        >
          <option value="auto">Public updates · optional free keys</option>
          <option value="offline">Offline · local only</option>
        </select>
        <select
          aria-label="Basemap"
          value={map}
          onChange={(e) => {
            void execute("earth.map.set", { mode: e.target.value as Basemap });
          }}
        >
          <option value="auto">Auto · detailed imagery</option>
          <option value="offline">Offline overview</option>
          <option value="satellite">Satellite imagery</option>
          <option value="streets">Street map</option>
        </select>
        <button
          className={cinematic ? "active" : ""}
          onClick={() => {
            setCinematic(!cinematic);
            controller.current?.cinematic(!cinematic);
          }}
        >
          ☼ Light
        </button>
      </nav>
      {mapStatus && (
        <div className={"map-status " + mapStatus.state} role="status">
          {mapStatus.message}
          {mapStatus.state === "fallback" && (
            <button
              onClick={() => {
                activeMap.current = null;
                syncBasemap(map);
              }}
            >
              Retry imagery
            </button>
          )}
        </div>
      )}
      {layersOpen && (
        <aside className="layers panel">
          <div className="panel-title">
            <div>
              <small>OBSERVATION LAYERS</small>
              <h2>Your view of Earth</h2>
            </div>
            <button
              aria-label="Collapse layers"
              onClick={() => setLayersOpen(false)}
            >
              ×
            </button>
          </div>
          <p className="muted intro">
            Works locally. Public sources refresh when online. Some optional
            sources use free keys. Zoom in for regional coverage.
          </p>
          <div className="layer-list">
            <PresencePanel
              controller={getController}
              at={scene?.timeline.at ?? null}
            />
            <MobilityPanel />
            <RasterWeatherPanel onSelect={(layer, cloud) => controller.current?.rasterWeather(layer, cloud)} />
            <PlanetaryPanel
              scene={scene}
              execute={execute}
              onProducts={onProducts}
            />
            {categories.map((layer) => {
              const values = providers.filter((p) => p.layer === layer);
              const enabled = values.some((p) => p.enabled);
              const activeProviders = values.filter((p) => p.enabled);
              const states = new Set(
                activeProviders.map((p) => p.health.state),
              );
              const healthState =
                states.size > 1 ? "degraded" : activeProviders[0]?.health.state;
              const healthLabel =
                activeProviders.length &&
                activeProviders.every(
                  (p) => p.health.error_code === "zoom_required",
                )
                  ? "zoom in"
                  : healthState;
              return (
                <div key={layer}>
                  {groups.find((group) => group.layers[0] === layer) && (
                    <h3 className="layer-group">
                      {groups.find((group) => group.layers[0] === layer)?.title}
                    </h3>
                  )}
                  <details className="layer-row">
                    <summary>
                      <label onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={enabled}
                          disabled={!values.length}
                          onChange={() => void toggleLayer(layer, enabled)}
                        />
                        <span>
                          {layerName(layer)}
                          {enabled && (
                            <small>
                              {(layerCounts[layer] ?? 0).toLocaleString()} in
                              view
                            </small>
                          )}
                        </span>
                      </label>
                      <span
                        className={
                          "health " + (enabled ? healthState : "disabled")
                        }
                      >
                        {enabled
                          ? healthLabel
                          : values.length
                            ? "off"
                            : "bridge"}
                      </span>
                    </summary>
                    <div className="layer-detail">
                      {layer === "space_weather" && enabled && (
                        <SpaceWeatherPanel />
                      )}
                      {values.length ? (
                        values.map((p) => (
                          <section key={p.id}>
                            <label>
                              <input
                                type="checkbox"
                                checked={p.enabled}
                                onChange={() =>
                                  void toggleLayer(p.id, p.enabled)
                                }
                              />{" "}
                              <strong>{p.label}</strong>
                            </label>
                            <p>{p.health.message}</p>
                            <p>{p.coverage}</p>
                            <small>
                              {p.attribution}
                              {p.local
                                ? " · local processing"
                                : p.credential
                                  ? " · optional free key"
                                  : " · public access, no key"}
                            </small>
                            {p.health.last_success_at && (
                              <small>
                                Updated {formatTime(p.health.last_success_at)}
                              </small>
                            )}
                          </section>
                        ))
                      ) : (
                        <p>
                          Local perception appears when 3000 publishes a
                          detection from a configured camera location.
                        </p>
                      )}
                    </div>
                  </details>
                </div>
              );
            })}
          </div>
          <footer className="layer-footer">
            <span className="status-dot" />
            {connection}
            <small>7-day history · 5 GiB rolling quota</small>
          </footer>
        </aside>
      )}
      <div className={"right-stack " + (daiseOpen ? "expanded" : "")}>
        {selected && (
          <aside className="inspector panel">
            <div className="panel-title">
              <div>
                <small>
                  {layerName(selected.layer)} / {selected.measurement_kind}
                </small>
                <h2>{label(selected)}</h2>
              </div>
              <button
                aria-label="Close inspector"
                onClick={() => {
                  setSelected(null);
                  setNearby([]);
                  controller.current?.select(null);
                }}
              >
                ×
              </button>
            </div>
            <div className="coordinate">
              {selected.position.latitude.toFixed(4)}° <span>/</span>{" "}
              {selected.position.longitude.toFixed(4)}°
            </div>
            <dl>
              <dt>Observed</dt>
              <dd>{formatTime(selected.observed_at)}</dd>
              <dt>Altitude</dt>
              <dd>
                {selected.position.altitude_m === null ||
                selected.position.altitude_m === undefined
                  ? "Unknown"
                  : Math.round(selected.position.altitude_m).toLocaleString() +
                    " m · " +
                    selected.position.altitude_reference}
              </dd>
              <dt>Speed</dt>
              <dd>
                {selected.motion?.speed_mps === null ||
                selected.motion?.speed_mps === undefined
                  ? "Unknown"
                  : selected.motion.speed_mps.toFixed(1) + " m/s"}
              </dd>
              <dt>Source</dt>
              <dd>
                <a href={selected.provenance.source_url} rel="noreferrer">
                  {selected.provenance.attribution}
                </a>
              </dd>
            </dl>
            <ObservationDetails observation={selected} />
            {selected.layer === "cctv" &&
              selected.properties?.stream_type !== "official_page" && (
                <>
                  {offline ? (
                    <p className="muted">
                      Live camera images are unavailable offline. This is the
                      stored camera location.
                    </p>
                  ) : (
                    <img
                      className="camera-image"
                      src={
                        "/api/camera-image?entity_id=" +
                        encodeURIComponent(selected.entity_id)
                      }
                      alt="Public camera still; source may be unavailable"
                      loading="lazy"
                    />
                  )}
                  <small>
                    Camera pose is uncalibrated. A still image is not continuous
                    live video.
                  </small>
                </>
              )}
            <div className="button-row">
              {(["follow", "orbit", "overhead"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() =>
                    void execute(`earth.camera.${mode}`, {
                      entity_id: selected.entity_id,
                      distance_m:
                        selected.layer === "satellites" ? 1000000 : 5000,
                    })
                  }
                >
                  {mode}
                </button>
              ))}
              <button onClick={() => void execute("earth.entity.untrack")}>
                Release
              </button>
            </div>
            <details>
              <summary>Source details</summary>
              <pre>{JSON.stringify(selected.properties, null, 2)}</pre>
            </details>
            {nearby.length > 0 && (
              <details>
                <summary>Nearby contacts · within 50 km</summary>
                {nearby
                  .filter((n) => n.observation.entity_id !== selected.entity_id)
                  .map((n) => (
                    <button
                      className="contact"
                      key={n.observation.entity_id}
                      onClick={() => void inspect(n.observation.entity_id)}
                    >
                      {label(n.observation)}
                      <small>{(n.distance_m / 1000).toFixed(1)} km</small>
                    </button>
                  ))}
              </details>
            )}
          </aside>
        )}
        {daiseOpen && (
          <aside className="daise panel">
            <div className="panel-title">
              <div>
                <small>OPERATOR ASSISTANCE</small>
                <h2>D.A.I.S.E.</h2>
              </div>
              <span className="cyan">✧</span>
            </div>
            <p className="muted">
              Evidence first. Explanations and suggested investigations stay
              separate from camera control.
            </p>
            <button
              className="primary wide"
              disabled={busy}
              onClick={() => void describe()}
            >
              {busy ? "Reviewing…" : "Describe this scene"}
            </button>
            <textarea
              className="wide"
              aria-label="Question for DAISE"
              placeholder="Ask the local model about this evidence…"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button
              className="wide"
              disabled={busy}
              onClick={() => void explainLocal()}
            >
              Explain with local model
            </button>
            {explanation && <p className="model-explanation">{explanation}</p>}
            {!situations.length && (
              <p className="empty">
                Bring an area into view, enable a layer, then ask for a scene
                summary.
              </p>
            )}
            {situations.map((s) => (
              <article className="situation" key={s.situation_id}>
                <h3>{s.summary}</h3>
                <small>
                  Latest observation {Math.round(s.freshness_seconds / 60)} min
                  ago
                </small>
                <p>{s.uncertainty}</p>
                <details>
                  <summary>{s.evidence.length} evidence references</summary>
                  {s.evidence.map((e, i) => (
                    <button
                      className="contact"
                      key={i}
                      onClick={() => void inspect(e.entity_id)}
                    >
                      {e.entity_id}
                      <small>{e.provider}</small>
                    </button>
                  ))}
                </details>
                <p className="suggestion">
                  Suggested: {s.suggestions.join(" · ")}
                </p>
              </article>
            ))}
          </aside>
        )}
      </div>
      <section className="bottom-controls">
        {error && (
          <div role="alert" className="error">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              ×
            </button>
          </div>
        )}
        <div className="scene-bar panel">
          <div>
            <span className="status-dot" />
            <strong>{scene?.timeline.at ? "REPLAY" : "EARTH"}</strong>
            <span className="muted">
              {contactCount.toLocaleString()} loaded ·{" "}
              {String(window.earthMetrics?.renderedTracks ?? 0)} shown
            </span>
          </div>
          <div className="button-row">
            <button
              onClick={() => {
                setTimelineOpen(!timelineOpen);
                if (!replay)
                  setReplay(
                    new Date(Date.now() - 3600000).toISOString().slice(0, 16),
                  );
              }}
            >
              ◷ Timeline
            </button>
            <button disabled={busy} onClick={() => void snapshot()}>
              ▣ Save scene
            </button>
            <button
              onClick={() => {
                setDiagnosticsOpen(!diagnosticsOpen);
                void loadDiagnostics();
              }}
            >
              ⋯ Diagnostics
            </button>
          </div>
        </div>
        {timelineOpen && (
          <div className="timeline panel">
            <label>
              Replay UTC
              <input
                type="datetime-local"
                value={replay}
                onChange={(e) => setReplay(e.target.value)}
              />
            </label>
            <button
              disabled={!replay || !Number.isFinite(Date.parse(replay + "Z"))}
              onClick={() =>
                void execute("earth.timeline.set", {
                  at: new Date(replay + "Z").toISOString(),
                })
              }
            >
              Set time
            </button>
            <button
              onClick={() =>
                void execute("earth.timeline.play", {
                  playing: !scene?.timeline.playing,
                  speed: 60,
                })
              }
            >
              {scene?.timeline.playing ? "Pause" : "Play 60×"}
            </button>
            <button
              onClick={() => void execute("earth.timeline.set", { at: null })}
            >
              Return to live
            </button>
            <span className="muted">
              {scene?.timeline.at ? formatTime(scene.timeline.at) : "Live view"}{" "}
              · gaps remain gaps
            </span>
          </div>
        )}
      </section>
      {diagnosticsOpen && (
        <aside className="diagnostics panel">
          <div className="panel-title">
            <h2>Workspace tools</h2>
            <button onClick={() => setDiagnosticsOpen(false)}>×</button>
          </div>
          <details open>
            <summary>Annotations</summary>
            <input
              aria-label="Annotation label"
              placeholder="Annotation label / saved scene name"
              value={annotationLabel}
              onChange={(e) => setAnnotationLabel(e.target.value)}
            />
            <select
              aria-label="Annotation shape"
              value={annotationGeometry}
              onChange={(e) =>
                setAnnotationGeometry(
                  e.target.value as typeof annotationGeometry,
                )
              }
            >
              <option value="point">Point</option>
              <option value="line">Line</option>
              <option value="polygon">Polygon</option>
            </select>
            <textarea
              aria-label="Annotation coordinates"
              placeholder="[[longitude, latitude], …] or use selected contact"
              value={annotationCoordinates}
              onChange={(e) => setAnnotationCoordinates(e.target.value)}
            />
            <button onClick={() => void annotate()}>Add annotation</button>
            {scene?.annotations.map((a) => (
              <div className="button-row" key={a.annotation_id}>
                <span>{a.label}</span>
                <button
                  onClick={() =>
                    void execute("earth.annotation.remove", {
                      annotation_id: a.annotation_id,
                    })
                  }
                >
                  Remove
                </button>
              </div>
            ))}
          </details>
          <details>
            <summary
              onClick={() =>
                void request<typeof views>("/api/investigations").then(setViews)
              }
            >
              Saved investigations
            </summary>
            <small>Saved separately from rolling history.</small>
            {views.map((v) => (
              <button
                className="contact"
                key={v.id}
                onClick={() => void restore(v.id)}
              >
                {v.label}
                <small>{formatTime(v.created)}</small>
              </button>
            ))}
          </details>
          <details>
            <summary
              onClick={() =>
                void execute("earth.watches.list").then((r) => {
                  if (r) setWatches(r.result as typeof watches);
                })
              }
            >
              Watched areas
            </summary>
            <p className="muted">
              Up to 10 areas. Polling sources rotate through this view and saved
              areas within their existing quotas.
            </p>
            <button
              onClick={() => {
                if (viewportRef.current)
                  void execute("earth.watch.add", {
                    name:
                      annotationLabel ||
                      "Area " + new Date().toLocaleTimeString(),
                    ...viewportRef.current,
                  }).then((r) => {
                    if (r) setWatches(r.result as typeof watches);
                  });
              }}
            >
              Watch this area
            </button>
            {watches.map((w) => (
              <div className="button-row" key={w.name}>
                <span>{w.name}</span>
                <button
                  onClick={() =>
                    void execute("earth.watch.remove", { name: w.name }).then(
                      (r) => {
                        if (r) setWatches(r.result as typeof watches);
                      },
                    )
                  }
                >
                  Remove
                </button>
              </div>
            ))}
          </details>
          <details>
            <summary>Loaded contacts</summary>
            {contacts.map((o) => (
              <button
                className="contact"
                key={o.entity_id}
                onClick={() => void inspect(o.entity_id)}
              >
                {label(o)}
                <small>{o.measurement_kind}</small>
              </button>
            ))}
          </details>
          <details>
            <summary>Runtime and provider diagnostics</summary>
            <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
          </details>
        </aside>
      )}
    </main>
  );
}
export default App;
