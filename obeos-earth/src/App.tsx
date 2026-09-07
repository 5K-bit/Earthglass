import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  buildModuleUrl,
  Cartesian2,
  Cartesian3,
  Color,
  LabelStyle,
  NearFarScalar,
  TileMapServiceImageryProvider,
  VerticalOrigin,
  Viewer,
  type Entity
} from "cesium";
import {
  getEarthquakes,
  refreshEarthquakes,
  type Earthquake,
  type EarthquakeFeed
} from "./api";

type LoadState = "loading" | "live" | "cached" | "degraded" | "error";

function magnitudeColor(magnitude: number | null): Color {
  if (magnitude === null) return Color.fromCssColorString("#75d7ff");
  if (magnitude >= 6) return Color.fromCssColorString("#ff3158");
  if (magnitude >= 4.5) return Color.fromCssColorString("#ff8a3d");
  if (magnitude >= 3) return Color.fromCssColorString("#ffd166");
  return Color.fromCssColorString("#51e1c2");
}

function pointSize(magnitude: number | null): number {
  return Math.max(6, Math.min(19, 6 + (magnitude ?? 0) * 1.8));
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit"
      }).format(parsed);
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>'"]/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        character
      ]!
  );
}

function App() {
  const globeRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const entityIndex = useRef(new Map<string, Entity>());
  const [feed, setFeed] = useState<EarthquakeFeed | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!globeRef.current) return;
    let cancelled = false;
    const viewer = new Viewer(globeRef.current, {
      animation: false,
      baseLayer: false,
      baseLayerPicker: false,
      fullscreenButton: false,
      geocoder: false,
      homeButton: true,
      infoBox: true,
      navigationHelpButton: false,
      sceneModePicker: false,
      selectionIndicator: true,
      timeline: false
    });
    viewerRef.current = viewer;
    viewer.scene.globe.baseColor = Color.fromCssColorString("#081324");
    viewer.scene.globe.enableLighting = true;
    viewer.scene.backgroundColor = Color.fromCssColorString("#030711");
    if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = true;

    void TileMapServiceImageryProvider.fromUrl(
      buildModuleUrl("Assets/Textures/NaturalEarthII")
    ).then((provider) => {
      if (!cancelled && !viewer.isDestroyed()) {
        viewer.imageryLayers.addImageryProvider(provider);
      }
    });

    viewer.camera.setView({
      destination: Cartesian3.fromDegrees(-20, 18, 21_000_000)
    });

    return () => {
      cancelled = true;
      entityIndex.current.clear();
      viewerRef.current = null;
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, []);

  const acceptFeed = useCallback((next: EarthquakeFeed) => {
    setFeed(next);
    setError(null);
    setState(next.stale ? "degraded" : next.cacheStatus === "cache" ? "cached" : "live");
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      getEarthquakes(controller.signal)
        .then(acceptFeed)
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setState((current) => (current === "loading" ? "error" : "degraded"));
          setError(reason instanceof Error ? reason.message : "EarthGlass is unavailable");
        });
    };
    load();
    const timer = window.setInterval(load, 300_000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [acceptFeed]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !feed) return;
    viewer.entities.removeAll();
    entityIndex.current.clear();

    for (const earthquake of feed.earthquakes) {
      const magnitude = earthquake.magnitude;
      const entity = viewer.entities.add({
        id: earthquake.id,
        name: earthquake.title,
        position: Cartesian3.fromDegrees(earthquake.longitude, earthquake.latitude, 2_000),
        point: {
          color: magnitudeColor(magnitude),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          distanceDisplayCondition: undefined,
          outlineColor: Color.fromCssColorString("#08101f"),
          outlineWidth: 2,
          pixelSize: pointSize(magnitude),
          scaleByDistance: new NearFarScalar(1_000_000, 1.35, 25_000_000, 0.72)
        },
        label:
          magnitude !== null && magnitude >= 5
            ? {
                text: `M${magnitude.toFixed(1)}`,
                font: "600 13px Inter, sans-serif",
                fillColor: Color.WHITE,
                outlineColor: Color.fromCssColorString("#030711"),
                outlineWidth: 3,
                style: LabelStyle.FILL_AND_OUTLINE,
                pixelOffset: new Cartesian2(0, -18),
                verticalOrigin: VerticalOrigin.BOTTOM,
                disableDepthTestDistance: Number.POSITIVE_INFINITY
              }
            : undefined,
        description: `
          <div style="font-family:system-ui;line-height:1.5;color:#132033">
            <h2 style="margin:0 0 8px">${escapeHtml(earthquake.title)}</h2>
            <p><strong>Observed:</strong> ${escapeHtml(formatTime(earthquake.observedAt))}</p>
            <p><strong>Depth:</strong> ${earthquake.depthKm?.toFixed(1) ?? "Unknown"} km</p>
            <p><a href="${escapeHtml(earthquake.sourceUrl)}" target="_blank" rel="noreferrer">Open USGS event</a></p>
          </div>`
      });
      entityIndex.current.set(earthquake.id, entity);
    }
  }, [feed]);

  const strongest = useMemo(
    () =>
      [...(feed?.earthquakes ?? [])]
        .sort((left, right) => (right.magnitude ?? -Infinity) - (left.magnitude ?? -Infinity))
        .slice(0, 8),
    [feed]
  );

  const refresh = async () => {
    setRefreshing(true);
    try {
      acceptFeed(await refreshEarthquakes());
    } catch (reason) {
      setState(feed ? "degraded" : "error");
      setError(reason instanceof Error ? reason.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const focusEarthquake = (earthquake: Earthquake) => {
    const viewer = viewerRef.current;
    const entity = entityIndex.current.get(earthquake.id);
    if (viewer && entity) {
      viewer.selectedEntity = entity;
      void viewer.flyTo(entity, { duration: 1.4 });
    }
  };

  return (
    <main className="app-shell">
      <div ref={globeRef} className="globe" aria-label="Interactive 3D Earth" />
      <div className="vignette" />

      <header className="topbar">
        <div className="brand-mark" aria-hidden="true"><span /></div>
        <div>
          <p className="eyebrow">OBEOS</p>
          <h1>EarthGlass</h1>
        </div>
        <div className={`connection connection--${state}`}>
          <span className="connection-dot" />
          {state === "loading" ? "Connecting" : state === "error" ? "Offline" : state}
        </div>
      </header>

      <aside className="world-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Live world layer</p>
            <h2>Seismic activity</h2>
          </div>
          <button type="button" onClick={refresh} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        <section className="metrics">
          <div><strong>{feed?.earthquakes.length ?? "—"}</strong><span>Events · 24h</span></div>
          <div><strong>{strongest[0]?.magnitude?.toFixed(1) ?? "—"}</strong><span>Strongest</span></div>
        </section>

        {error && <div className="error-banner">{error}</div>}
        {state === "degraded" && (
          <div className="warning-banner">USGS is unavailable. Showing the last validated cache.</div>
        )}

        <div className="event-list" aria-label="Strongest recent earthquakes">
          {strongest.map((earthquake) => (
            <button
              className="event-row"
              key={earthquake.id}
              onClick={() => focusEarthquake(earthquake)}
              type="button"
            >
              <span className="magnitude">{earthquake.magnitude?.toFixed(1) ?? "?"}</span>
              <span className="event-copy">
                <strong>{earthquake.place}</strong>
                <small>{formatTime(earthquake.observedAt)} · {earthquake.depthKm?.toFixed(1) ?? "?"} km deep</small>
              </span>
            </button>
          ))}
          {state === "loading" && <p className="loading-copy">Reading EarthGlass world state…</p>}
        </div>

        <footer>
          <span>{feed?.attribution ?? "U.S. Geological Survey (USGS)"}</span>
          <span>{feed ? `Updated ${formatTime(feed.generatedAt)}` : "Awaiting feed"}</span>
        </footer>
      </aside>

      <div className="legend" aria-label="Magnitude legend">
        <span><i className="dot dot--minor" />Minor</span>
        <span><i className="dot dot--moderate" />Moderate</span>
        <span><i className="dot dot--strong" />Strong</span>
      </div>
    </main>
  );
}

export default App;
