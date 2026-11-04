import { useEffect, useRef, useState } from "react";
import {
  Cartesian3, Color, Credit, EllipsoidTerrainProvider, Rectangle,
  SingleTileImageryProvider, TileMapServiceImageryProvider, Viewer,
} from "cesium";
import type { ImageryLayer } from "cesium";
import { assessCatalog, assessLayer, type WeatherLayer } from "./broadcastData";
import "./broadcast.css";

type Location = { id: string; city: string; region: string; heading: string; lon: number; lat: number; distance: number };
const locations: Location[] = [
  { id: "nyc", city: "NEW YORK", region: "NORTHEAST", heading: "Regional Weather Overview", lon: -74.006, lat: 40.713, distance: 3900000 },
  { id: "mia", city: "MIAMI", region: "ATLANTIC COAST", heading: "Atlantic Weather Watch", lon: -80.192, lat: 25.762, distance: 4900000 },
  { id: "chi", city: "CHICAGO", region: "MIDWEST", heading: "Regional Conditions", lon: -87.63, lat: 41.88, distance: 4300000 },
  { id: "sf", city: "SAN FRANCISCO", region: "WEST COAST", heading: "Pacific Weather Overview", lon: -122.42, lat: 37.77, distance: 4000000 },
];
const fields = [
  { id: "temperature", label: "Temperature" },
  { id: "precipRate", label: "Precipitation" },
  { id: "wind10m", label: "Wind" },
  { id: "cloudCover", label: "Cloud cover" },
  { id: "pressure", label: "Air pressure" },
  { id: "humidity", label: "Humidity" },
];
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

export default function BroadcastStudio() {
  const globeNode = useRef<HTMLDivElement>(null);
  const programNode = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const overlay = useRef<ImageryLayer | null>(null);
  const [location, setLocation] = useState<Location>(locations[0]);
  const [field, setField] = useState("temperature");
  const [catalog, setCatalog] = useState<WeatherLayer[]>([]);
  const [connection, setConnection] = useState("Connecting to EarthGlass");
  const [error, setError] = useState("");
  const programOnly = new URLSearchParams(window.location.search).get("program") === "1";
  const assessment = assessLayer(catalog.find(item => item.id === field));
  const illustrative = assessment.state === "demo" || assessment.state === "unsupported";
  const sourceDescription = illustrative ? "ILLUSTRATIVE DATA · NOT A FORECAST" :
    assessment.state === "stale" ? "STALE MODEL · NOT FOR AIR" :
    "NOAA GFS MODEL ANALYSIS · REVIEW REQUIRED";

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
    scene.camera.setView({ destination: Cartesian3.fromDegrees(-74.006, 40.713, 3900000) });
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

  useEffect(() => {
    let active = true;
    let pending: AbortController | null = null;
    const load = async () => {
      pending?.abort();
      pending = new AbortController();
      try {
        const response = await fetch(API_ORIGIN + "/api/weather/layers", {
          signal: pending.signal, headers: { Accept: "application/json" }, cache: "no-store",
        });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const layers = assessCatalog(await response.json());
        if (!active) return;
        setCatalog(layers);
        setConnection("EarthGlass weather API connected");
      } catch {
        if (!active || pending.signal.aborted) return;
        setCatalog([]);
        setConnection("EarthGlass weather API unavailable · sample mode");
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => { active = false; pending?.abort(); clearInterval(timer); };
  }, []);

  useEffect(() => {
    const scene = viewer.current;
    if (!scene || scene.isDestroyed()) return;
    let active = true;
    const image = illustrative ? illustrativeTexture(field) :
      API_ORIGIN + assessment.asset;
    void SingleTileImageryProvider.fromUrl(image, {
      rectangle: Rectangle.MAX_VALUE,
      credit: new Credit(illustrative ? "SIMULATED WEATHER GRAPHIC · NOT REAL DATA" : "NOAA GFS via EarthGlass", true),
    }).then(provider => {
      if (!active || scene.isDestroyed()) return;
      if (overlay.current) scene.imageryLayers.remove(overlay.current, true);
      overlay.current = scene.imageryLayers.addImageryProvider(provider);
      overlay.current.alpha = illustrative ? 0.68 : 0.78;
      setError("");
      scene.scene.requestRender();
    }).catch(() => {
      if (active) setError("Weather overlay unavailable. Check the EarthGlass image endpoint.");
    });
    return () => { active = false; };
  }, [field, catalog, assessment.asset, illustrative]);

  const take = (item: Location) => {
    setLocation(item);
    viewer.current?.camera.flyTo({
      destination: Cartesian3.fromDegrees(item.lon, item.lat, item.distance),
      duration: 1.6,
    });
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
          <div className="program-lower">
            <div className="program-overline">{location.region} / {fields.find(item => item.id === field)?.label.toUpperCase()}</div>
            <div className="program-title">{location.heading}</div>
            <div className="program-bottom"><span>{location.city}</span><span>{assessment.cycle ? "MODEL CYCLE " + formatCycle(assessment.cycle) : "SYNTHETIC WEATHER VISUALIZATION"}</span></div>
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
          <select id="weather-product" value={field} onChange={event => setField(event.target.value)}>
            {fields.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <p className="source-description">{sourceDescription}</p>
          <p className="source-status">{connection}</p>
          <div className="control-caption">03 / OUTPUT</div>
          <div className="actions">
            <button type="button" onClick={() => window.open("/broadcast.html?program=1", "_blank", "noopener")}>
              Open clean 16:9 preview
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
