import { useEffect, useRef, useState } from "react";
import { request } from "./controlApi";

export type RasterWeather = {
  id: string; name: string; unit: string; offline: boolean;
  refreshing: boolean; error?: string;
  metadata?: { cycle: string; generatedAt?: string; assets: { image: string } };
};
export function RasterWeatherPanel({ onSelect }: {
  onSelect: (layer: RasterWeather | null, cloud: boolean) => Promise<void> | void;
}) {
  const [layers, setLayers] = useState<RasterWeather[]>([]);
  const [error, setError] = useState("");
  const [renderErrors, setRenderErrors] = useState({primary: "", cloud: ""});
  const [selected, setSelected] = useState("");
  const [cloud, setCloud] = useState(false);
  const [retry, setRetry] = useState(0);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  // Catalog polling returns new objects; only reload imagery when the product changes.
  const primaryProduct = JSON.stringify(layers.find(layer => layer.id === selected)?.metadata ?? null);
  const cloudProduct = JSON.stringify(layers.find(layer => layer.id === "cloudCover")?.metadata ?? null);
  useEffect(() => {
    let active = true;
    const refresh = () => request<RasterWeather[]>("/api/weather/layers")
      .then(value => { if (active) { setLayers(value); setError(""); } })
      .catch(() => { if (active) setError("Weather catalog unavailable"); });
    void refresh();
    const timer = setInterval(refresh, 10000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  useEffect(() => {
    let active = true;
    setRenderErrors(value => ({...value, primary: ""}));
    Promise.resolve().then(() => selectRef.current(layers.find(layer => layer.id === selected) ?? null, false))
      .catch(() => { if (active) setRenderErrors(value => ({...value, primary: "Weather imagery could not load. Retry the layer."})); });
    return () => { active = false; };
  }, [selected, primaryProduct, retry]);
  useEffect(() => {
    let active = true;
    setRenderErrors(value => ({...value, cloud: ""}));
    Promise.resolve().then(() => selectRef.current(cloud ? layers.find(layer => layer.id === "cloudCover") ?? null : null, true))
      .catch(() => { if (active) setRenderErrors(value => ({...value, cloud: "Cloud imagery could not load. Retry the layer."})); });
    return () => { active = false; };
  }, [cloud, cloudProduct, retry]);
  return <details className="layer-row"><summary>NOAA weather globe</summary>
    <p>GFS model analysis · retained cycle, not live observation</p>
    <label>Weather field <select value={selected} onChange={event => setSelected(event.target.value)}>
      <option value="">None</option>{layers.filter(layer => layer.id !== "cloudCover").map(layer =>
      <option key={layer.id} value={layer.id} disabled={!layer.metadata}>{layer.name} ({layer.unit})</option>)}</select></label>
    <label><input type="checkbox" checked={cloud}
      disabled={!layers.find(layer => layer.id === "cloudCover")?.metadata}
      onChange={event => setCloud(event.target.checked)} />Cloud cover</label>
    {layers.map(layer => <div key={layer.id}><small>{layer.name}: {layer.metadata?.cycle ?? "No local data"}
      {layer.offline ? " · offline cache" : ""}{layer.error ? " · " + layer.error : ""}</small>
      <button disabled={layer.offline || layer.refreshing} onClick={() => {
        setLayers(current => current.map(item => item.id === layer.id ? {...item, refreshing: true} : item));
        void request("/api/weather/layers/" + layer.id + "/refresh", {method: "POST"})
          .catch(() => { setError("Weather refresh failed"); setLayers(current => current.map(item => item.id === layer.id ? {...item, refreshing: false} : item)); });
      }}>{layer.refreshing ? "Refreshing…" : "Refresh"}</button></div>)}
    {error && <p role="status">{error}</p>}
    {(renderErrors.primary || renderErrors.cloud) && <div role="status">
      <p>{renderErrors.primary} {renderErrors.cloud}</p><button onClick={() => setRetry(value => value + 1)}>Retry imagery</button>
    </div>}
  </details>;
}
