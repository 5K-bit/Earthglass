import { useEffect, useMemo, useRef, useState } from "react";
import {
  Cartesian3, Color, Credit, EllipsoidTerrainProvider, PolygonHierarchy, Rectangle,
  SingleTileImageryProvider, TileMapServiceImageryProvider, Viewer,
} from "cesium";
import type { Entity, ImageryLayer } from "cesium";
import { assessCatalog, assessLayer, overlayUrl, type WeatherLayer } from "./broadcastData";
import {
  alertPolygons, assessAlertBanner, assessRadar, parseAlerts,
  type AlertFeature, type AlertFeed, type RadarMeta,
} from "./broadcastAlerts";
import { CONTROL_POLL_MS, controlLink, nextProgram, parseProgram, type ProgramState } from "./broadcastControl";
import "./broadcast.css";

type Location = { id: string; city: string; region: string; heading: string; lon: number; lat: number; distance: number };
const locations: Location[] = [
  { id: "nyc", city: "NEW YORK", region: "NORTHEAST", heading: "Regional Weather Overview", lon: -74.006, lat: 40.713, distance: 3900000 },
  { id: "mia", city: "MIAMI", region: "ATLANTIC COAST", heading: "Atlantic Weather Watch", lon: -80.192, lat: 25.762, distance: 4900000 },
  { id: "chi", city: "CHICAGO", region: "MIDWEST", heading: "Regional Conditions", lon: -87.63, lat: 41.88, distance: 4300000 },
  { id: "sf", city: "SAN FRANCISCO", region: "WEST COAST", heading: "Pacific Weather Overview", lon: -122.42, lat: 37.77, distance: 4000000 },
];
const fields = [
  { id: "radar", label: "Radar (observed)" },
  { id: "temperature", label: "Temperature" },
  { id: "precipRate", label: "Precipitation" },
  { id: "wind10m", label: "Wind" },
  { id: "cloudCover", label: "Cloud cover" },
  { id: "pressure", label: "Air pressure" },
  { id: "humidity", label: "Humidity" },
];
const SEVERITY_COLOR: Record<string, string> = {
  Extreme: "#ff3b5c", Severe: "#ff9a3c", Moderate: "#ffd23c", Minor: "#5cc8ff",
};
const API_ORIGIN = String(import.meta.env.VITE_BROADCAST_API_ORIGIN || "").replace(/\/$/, "");

function illustrativeTexture(kind: string): string {
  const canvas = document.createElement("canvas");
  canvas.width = 720;
  canvas.height = 360;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas graphics unavailable");
  const pixels = ctx.createImageData(canvas.width, canvas.height);
  for (let y = 0; y < canvas.height; y++) {
    for (let x = 0; x < canvas.width; x++) {
      const longitude = (x / canvas.width) * Math.PI * 2;
      const latitude = ((y / canvas.height) - 0.5) * Math.PI;
      const wave = 0.5 + 0.26 * Math.sin(longitude * 3 + Math.cos(latitude * 5))
        + 0.21 * Math.sin(longitude * 9 - latitude * 4);
      const v = Math.max(0, Math.min(1, wave));
      const i = (y * canvas.width + x) * 4;
      if (kind === "temperature") {
        pixels.data[i] = Math.round(245 * v + 25);
        pixels.data[i + 1] = Math.round(154 - 85 * v);
        pixels.data[i + 2] = Math.round(223 * (1 - v));
      } else if (kind === "wind10m") {
        pixels.data[i] = 51;
        pixels.data[i + 1] = Math.round(122 + 110 * v);
        pixels.data[i + 2] = 230;
      } else if (kind === "precipRate" || kind === "cloudCover") {
        pixels.data[i] = Math.round(25 + v * 85);
        pixels.data[i + 1] = Math.round(155 + v * 70);
        pixels.data[i + 2] = 250;
      } else {
        pixels.data[i] = Math.round(75 + v * 120);
        pixels.data[i + 1] = Math.round(135 + v * 75);
        pixels.data[i + 2] = Math.round(185 + v * 48);
      }
      pixels.data[i + 3] = v > 0.57 ? Math.round(90 + v * 100) : 0;
    }
  }
  ctx.putImageData(pixels, 0, 0);
  return canvas.toDataURL("image/png");
}

function formatCycle(cycle: string | null): string {
  if (!cycle) return "NO LIVE DATA";
  const parsed = new Date(cycle);
  return Number.isNaN(parsed.getTime()) ? "UNKNOWN CYCLE" :
    parsed.toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) + " UTC";
}

// Initial shot / product from the URL (validated), so an OBS browser source can open straight onto a scene.
const startParams = new URLSearchParams(window.location.search);
const startLocation = locations.find(item => item.id === startParams.get("scene")) ?? locations[0];
const startField = fields.find(item => item.id === startParams.get("field"))?.id ?? "temperature";

export default function BroadcastStudio() {
  const globeNode = useRef<HTMLDivElement>(null);
  const programNode = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const overlay = useRef<ImageryLayer | null>(null);
  const broadcast = useRef<BroadcastChannel | null>(null);
  const currentScene = useRef(startLocation.id);
  const currentField = useRef(startField);
  const [location, setLocation] = useState<Location>(startLocation);
  const [field, setField] = useState(startField);
  const [catalog, setCatalog] = useState<WeatherLayer[]>([]);
  const [connection, setConnection] = useState("Connecting to EarthGlass");
  const [error, setError] = useState("");
  const [lastFetchMs, setLastFetchMs] = useState<number | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [radarMeta, setRadarMeta] = useState<RadarMeta | null>(null);
  const [radarFetchMs, setRadarFetchMs] = useState<number | null>(null);
  const [cityAlerts, setCityAlerts] = useState<AlertFeed & { cityId: string }>({ features: [], lastFetchMs: null, ok: false, cityId: "" });
  const [mapAlerts, setMapAlerts] = useState<AlertFeature[]>([]);
  const alertEntities = useRef<Entity[]>([]);
  const programOnly = new URLSearchParams(window.location.search).get("program") === "1";
  const [controlOk, setControlOk] = useState<number | null>(null);
  const [onAir, setOnAir] = useState<ProgramState | null>(null);
  const [controlError, setControlError] = useState("");
  const assessment = assessLayer(catalog.find(item => item.id === field), nowMs, lastFetchMs);
  const isRadar = field === "radar";
  const radar = assessRadar(radarMeta, nowMs, radarFetchMs);
  const illustrative = !isRadar && (assessment.state === "demo" || assessment.state === "unsupported");
  // Alerts for another city are never shown: a switch resets to "checking" until this city's data lands.
  const cityFeed: AlertFeed = cityAlerts.cityId === location.id ? cityAlerts : { features: [], lastFetchMs: null, ok: false };
  const banner = assessAlertBanner(cityFeed, location.city, nowMs);
  const radarImage = radar.image;
  const radarObservedAt = radar.observedAt;
  const radarRectangle = useMemo(() => radar.rectangle, [radar.rectangle?.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const radarTime = radar.observedAt ? formatCycle(radar.observedAt) : "";
  const sourceDescription = isRadar ? radar.description + (radarTime ? " · " + radarTime : "") : illustrative ? "ILLUSTRATIVE DATA · NOT A FORECAST" :
    assessment.state === "stale" ? "STALE MODEL · NOT FOR AIR" :
    "NOAA GFS MODEL ANALYSIS · REVIEW REQUIRED";

  // Same-browser preview synchronization only. OBS / separate hosts need server transport.
  useEffect(() => {
    if (!("BroadcastChannel" in window)) return;
    const bus = new BroadcastChannel("earthglass-broadcast-preview-v1");
    broadcast.current = bus;
    bus.onmessage = event => {
      const message: unknown = event.data;
      if (!message || typeof message !== "object") return;
      const payload = message as { type?: string; scene?: string; field?: string };
      if (payload.type === "hello" && !programOnly) {
        bus.postMessage({ type: "sync", scene: currentScene.current, field: currentField.current });
      }
      if (programOnly && (payload.type === "sync" || payload.type === "scene")) {
        const shot = locations.find(item => item.id === payload.scene);
        if (shot) {
          currentScene.current = shot.id;
          setLocation(shot);
        }
        if (fields.some(item => item.id === payload.field)) {
          currentField.current = payload.field!;
          setField(payload.field!);
        }
      }
    };
    if (programOnly) bus.postMessage({ type: "hello" });
    return () => { broadcast.current = null; bus.close(); };
  }, [programOnly]);

  // Server-held on-air state: the program output (including an OBS Browser Source) follows it.
  useEffect(() => {
    let active = true;
    const sceneIds = locations.map(item => item.id);
    const fieldIds = fields.map(item => item.id);
    const poll = async () => {
      try {
        const response = await fetch(API_ORIGIN + "/api/broadcast/program", { headers: { Accept: "application/json" }, cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const next = parseProgram(await response.json(), sceneIds, fieldIds);
        if (!active) return;
        setControlOk(Date.now());
        setOnAir(previous => {
          const chosen = nextProgram(previous, next);
          if (programOnly && chosen && chosen !== previous) {
            const shot = locations.find(item => item.id === chosen.scene);
            if (shot) { currentScene.current = shot.id; setLocation(shot); }
            currentField.current = chosen.field;
            setField(chosen.field);
          }
          return chosen;
        });
      } catch {
        // Keep the last on-air state; the control room shows the lost link.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), CONTROL_POLL_MS);
    return () => { active = false; window.clearInterval(timer); };
  }, [programOnly]);

  useEffect(() => {
    if (!globeNode.current) return;
    let scene: Viewer;
    try {
      scene = new Viewer(globeNode.current, {
        animation: false, timeline: false, baseLayerPicker: false, baseLayer: false,
        geocoder: false, homeButton: false, sceneModePicker: false,
        navigationHelpButton: false, fullscreenButton: false,
        infoBox: false, selectionIndicator: false,
        terrainProvider: new EllipsoidTerrainProvider(),
        contextOptions: { webgl: { preserveDrawingBuffer: true, alpha: false } },
        requestRenderMode: true,
      });
    } catch {
      setError("3D renderer could not start. Check WebGL and graphics acceleration.");
      return;
    }
    viewer.current = scene;
    scene.scene.backgroundColor = Color.fromCssColorString("#050b17");
    scene.scene.globe.baseColor = Color.fromCssColorString("#193146");
    scene.scene.globe.enableLighting = false;
    scene.scene.fog.enabled = false;
    scene.scene.globe.maximumScreenSpaceError = 3;
    scene.camera.setView({ destination: Cartesian3.fromDegrees(startLocation.lon, startLocation.lat, startLocation.distance) });
    const assetRoot = import.meta.env.DEV ? "/node_modules/cesium/Build/Cesium" : "/cesium";
    void TileMapServiceImageryProvider.fromUrl(assetRoot + "/Assets/Textures/NaturalEarthII", {
      credit: new Credit("Natural Earth · public domain, bundled with Cesium", true),
    }).then(provider => {
      if (!scene.isDestroyed()) scene.imageryLayers.addImageryProvider(provider, 0);
    }).catch(() => setError("Bundled geographic imagery unavailable."));
    scene.scene.renderError.addEventListener(() => setError("3D renderer encountered an error."));
    return () => {
      viewer.current = null;
      overlay.current = null;
      if (!scene.isDestroyed()) scene.destroy();
    };
  }, []);

  // Re-evaluate freshness continuously, not only when something else re-renders.
  useEffect(() => {
    const tick = window.setInterval(() => setNowMs(Date.now()), 5000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    let active = true;
    let pending: AbortController | null = null;
    const load = async () => {
      pending?.abort();
      const controller = new AbortController();
      pending = controller;
      try {
        const response = await fetch(API_ORIGIN + "/api/weather/layers", {
          signal: controller.signal, headers: { Accept: "application/json" }, cache: "no-store",
        });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const layers = assessCatalog(await response.json());
        if (!active) return;
        setCatalog(layers);
        setLastFetchMs(Date.now());
        setConnection("EarthGlass weather API connected");
      } catch {
        if (!active || controller.signal.aborted) return;
        setCatalog([]);
        setConnection("EarthGlass weather API unavailable · sample mode");
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => { active = false; pending?.abort(); clearInterval(timer); };
  }, []);

  // Radar: observed frame metadata, polled every 60 s. Failure keeps the last frame, which then ages to "stale".
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(API_ORIGIN + "/api/weather/radar", { headers: { Accept: "application/json" }, cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const meta = (await response.json()) as RadarMeta;
        if (!active) return;
        setRadarMeta(meta);
        setRadarFetchMs(Date.now());
      } catch { /* keep the last frame; freshness rules age it out */ }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  // Alerts for the current shot, resolved by NWS (includes zone-only alerts with no polygon).
  useEffect(() => {
    let active = true;
    const cityId = location.id;
    const load = async () => {
      try {
        const query = "?lat=" + location.lat.toFixed(4) + "&lon=" + location.lon.toFixed(4);
        const response = await fetch(API_ORIGIN + "/api/weather/alerts/point" + query, { headers: { Accept: "application/json" }, cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const features = parseAlerts(await response.json());
        if (active) setCityAlerts({ features, lastFetchMs: Date.now(), ok: true, cityId });
      } catch { /* banner turns to "unavailable" once the last success is older than the freshness limit */ }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => { active = false; clearInterval(timer); };
  }, [location]);

  // Alert areas for the globe (only alerts that ship a polygon).
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(API_ORIGIN + "/api/layers/weather-alerts/features", { headers: { Accept: "application/json" }, cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const features = parseAlerts(await response.json());
        if (active) setMapAlerts(features);
      } catch { /* leave previous areas; expiry still removes them */ }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  const alertMinute = Math.floor(nowMs / 60000);
  useEffect(() => {
    const scene = viewer.current;
    if (!scene || scene.isDestroyed()) return;
    alertEntities.current.forEach(entity => scene.entities.remove(entity));
    alertEntities.current = alertPolygons(mapAlerts, alertMinute * 60000).map(item => {
      const color = Color.fromCssColorString(SEVERITY_COLOR[item.severity] ?? "#9fb5c1");
      return scene.entities.add({
        id: "alert:" + item.id,
        polygon: { hierarchy: new PolygonHierarchy(Cartesian3.fromDegreesArray(item.positions)),
          material: color.withAlpha(0.2), outline: true, outlineColor: color, height: 0 },
      });
    });
    scene.scene.requestRender();
  }, [mapAlerts, alertMinute]);

  useEffect(() => {
    const scene = viewer.current;
    if (!scene || scene.isDestroyed()) return;
    let active = true;
    const clearOverlay = () => {
      if (overlay.current) { scene.imageryLayers.remove(overlay.current, true); overlay.current = null; scene.scene.requestRender(); }
    };
    let image: string | null;
    let rectangle = Rectangle.MAX_VALUE;
    let credit: string;
    if (isRadar) {
      // There is no honest synthetic stand-in for radar: with no valid frame, show nothing.
      if (!radarImage || !radarRectangle) { clearOverlay(); return; }
      image = API_ORIGIN + radarImage + "?t=" + encodeURIComponent(radarObservedAt ?? "");
      rectangle = Rectangle.fromDegrees(...radarRectangle);
      credit = "NOAA radar via EarthGlass";
    } else {
      image = illustrative ? illustrativeTexture(field) : overlayUrl(API_ORIGIN, assessment);
      credit = illustrative ? "SIMULATED WEATHER GRAPHIC · NOT REAL DATA" : "NOAA GFS via EarthGlass";
    }
    if (!image) { clearOverlay(); return; }
    void SingleTileImageryProvider.fromUrl(image, { rectangle, credit: new Credit(credit, true) }).then(provider => {
      if (!active || scene.isDestroyed()) return;
      if (overlay.current) scene.imageryLayers.remove(overlay.current, true);
      overlay.current = scene.imageryLayers.addImageryProvider(provider);
      overlay.current.alpha = isRadar ? 0.85 : illustrative ? 0.68 : 0.78;
      setError("");
      scene.scene.requestRender();
    }).catch(() => {
      if (active) setError(isRadar ? "Radar overlay unavailable." : "Weather overlay unavailable. Check the EarthGlass image endpoint.");
    });
    return () => { active = false; };
    // Keyed on the asset URL / observation time, not the polled objects, so a poll never reloads the overlay.
  }, [field, isRadar, assessment.asset, assessment.cycle, illustrative, radarImage, radarObservedAt, radarRectangle]);

  useEffect(() => {
    const scene = viewer.current;
    if (!scene || scene.isDestroyed()) return;
    scene.camera.flyTo({
      destination: Cartesian3.fromDegrees(location.lon, location.lat, location.distance),
      duration: 1.35,
    });
  }, [location]);

  const publish = async (scene: string, nextField: string) => {
    const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "application/json" };
    const token = window.localStorage.getItem("earthglass-control-token");
    if (token) headers["X-Control-Token"] = token;
    try {
      const response = await fetch(API_ORIGIN + "/api/broadcast/program", { method: "POST", headers, body: JSON.stringify({ scene, field: nextField }) });
      if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? "Control refused (" + response.status + ")" : "HTTP " + response.status);
      setControlError("");
    } catch (failure) {
      setControlError("Program output NOT updated: " + (failure instanceof Error ? failure.message : "link down"));
    }
  };
  const take = (item: Location) => {
    currentScene.current = item.id;
    setLocation(item);
    broadcast.current?.postMessage({ type: "scene", scene: item.id, field: currentField.current });
    void publish(item.id, currentField.current);
  };
  const selectField = (nextField: string) => {
    currentField.current = nextField;
    setField(nextField);
    broadcast.current?.postMessage({ type: "scene", scene: currentScene.current, field: nextField });
    void publish(currentScene.current, nextField);
  };

  return (
    <main className={programOnly ? "broadcast-shell program-only" : "broadcast-shell"}>
      {!programOnly && <header className="studio-head">
        <div><span className="brand-symbol">◉</span><strong>EARTHGLASS</strong><span className="brand-sub">/ BROADCAST</span></div>
        <span className="studio-kicker">BY OBEOS · BROADCAST PROTOTYPE V0.1</span>
      </header>}
      <div className="studio-layout">
        <section className="program-frame" aria-label="16 by 9 broadcast presentation preview" ref={programNode}>
          <div className="globe-viewport" ref={globeNode} />
          <div className="program-shade" />
          <div className="program-top">
            <span className="program-brand"><b>EG</b> EARTHGLASS <em>WEATHER</em></span>
            <span className="program-pill">PROTOTYPE / NOT FOR AIR</span>
          </div>
          <div className="program-stamp">{sourceDescription}</div>
          <div className={"program-alert alert-" + banner.state} role="status" data-severity={banner.severity ?? ""}>
            <b>{banner.state === "alert" ? "⚠ " : ""}{banner.headline}</b>
            <span>{banner.detail}{banner.count > 1 ? " · +" + (banner.count - 1) + " MORE" : ""}</span>
          </div>
          <div className="program-lower">
            <div className="program-overline">{location.region} / {fields.find(item => item.id === field)?.label.toUpperCase()}</div>
            <div className="program-title">{location.heading}</div>
            <div className="program-bottom"><span>{location.city}</span><span>{isRadar ? (radar.observedAt ? "RADAR OBSERVED " + formatCycle(radar.observedAt) : "NO RADAR DATA") : assessment.cycle ? "MODEL CYCLE " + formatCycle(assessment.cycle) : "SYNTHETIC WEATHER VISUALIZATION"}</span></div>
          </div>
          {error && <p role="status" className="program-error">{error}</p>}
        </section>
        {!programOnly && <aside className="studio-controls">
          <div className="control-caption">01 / SHOT SELECTOR</div>
          <h2>Weather stories</h2>
          <p>Choose a location and take the camera to air-preview.</p>
          <div className="shots">{locations.map(item =>
            <button key={item.id} type="button" onClick={() => take(item)}
              className={location.id === item.id ? "shot active" : "shot"}>
              <small>{item.region}</small><strong>{item.city}</strong><span>TAKE</span>
            </button>)}</div>
          <div className="control-caption">02 / ATMOSPHERIC PRODUCT</div>
          <label htmlFor="weather-product">Weather field</label>
          <select id="weather-product" value={field} onChange={event => selectField(event.target.value)}>
            {fields.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <p className="source-description">{sourceDescription}</p>
          <p className="source-status">{connection}</p>
          <p className={"control-status link-" + controlLink(controlOk, nowMs)} role="status">
            {controlError ? controlError :
              controlLink(controlOk, nowMs) === "ok" ? (onAir ? "ON AIR (server): " + onAir.scene.toUpperCase() + " / " + onAir.field + " · rev " + onAir.revision : "Server link OK · nothing taken yet") :
              controlLink(controlOk, nowMs) === "lost" ? "CONTROL LINK LOST · OBS output is holding its last shot" : "Connecting to program control"}
          </p>
          <div className="control-caption">03 / OUTPUT</div>
          <div className="actions">
            <button type="button" onClick={() => window.open("/broadcast.html?program=1", "_blank", "noopener")}>
              Open clean 16:9 output (follows server)
            </button>
            <button type="button" onClick={() => void programNode.current?.requestFullscreen()}>
              Fullscreen preview
            </button>
          </div>
          <p className="safety-note">Demo footage is clearly watermarked. The NOAA GFS f000 product is model analysis, not radar observation. No scene is certified for live broadcast.</p>
        </aside>}
      </div>
      {!programOnly && <footer className="studio-footer">
        <span>EARTHGLASS / GEOSPATIAL ENGINE + OBEOS EARTH / CESIUM RENDERER</span>
        <span>DATA PROVENANCE FIRST · BROADCAST INTEGRATION NEXT</span>
      </footer>}
    </main>
  );
}
