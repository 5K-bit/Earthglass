import { useEffect, useState } from "react";
import { request } from "./controlApi";
import type { SceneState, ControlResult } from "./controlApi";
import type { ImageryProduct } from "./imageryController";
import type { EarthArguments } from "./earthControl.generated";

type Execute = <K extends keyof EarthArguments>(
  name: K,
  args: EarthArguments[K],
) => Promise<ControlResult | null>;
export function PlanetaryPanel({
  scene,
  execute,
  onProducts,
}: {
  scene: SceneState | null;
  execute: Execute;
  onProducts: (products: ImageryProduct[]) => void;
}) {
  const [products, setProducts] = useState<ImageryProduct[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const refresh = () =>
      request<{ data: ImageryProduct[] }>("/api/v2/imagery/catalog")
        .then((value) => {
          if (active) {
            setProducts(value.data);
            onProducts(value.data);
          }
        })
        .catch(() => {
          if (active) setError("Imagery catalog unavailable");
        });
    void refresh();
    const timer = setInterval(() => void refresh(), 60000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [onProducts]);
  return (
    <details className="layer-row">
      <summary>
        Satellite imagery <small> · up to 2 overlays</small>
      </summary>
      <div className="layer-detail">
        {products.map((p) => (
          <label key={p.id} style={{ display: "block", marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={!!scene?.imagery?.some((v) => v.product === p.id)}
              disabled={!p.available}
              onChange={(e) =>
                void execute("earth.imagery.set", {
                  product:
                    p.id as EarthArguments["earth.imagery.set"]["product"],
                  enabled: e.target.checked,
                  opacity: 0.7,
                })
              }
            />
            {p.label}
            {scene?.imagery?.some((v) => v.product === p.id) && (
              <input
                aria-label={p.label + " opacity"}
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={
                  scene.imagery.find((v) => v.product === p.id)?.opacity ?? 0.7
                }
                onChange={(e) =>
                  void execute("earth.imagery.set", {
                    product:
                      p.id as EarthArguments["earth.imagery.set"]["product"],
                    enabled: true,
                    opacity: Number(e.target.value),
                  })
                }
              />
            )}
            <small style={{ display: "block" }}>
              {p.available ? p.default_time : "Source unavailable"} ·{" "}
              {p.provider}
            </small>
          </label>
        ))}
        {error && <p role="status">{error}</p>}
        <p className="muted">
          Frames follow the timeline. Offline views use only tiles already
          cached; gaps remain visible.
        </p>
      </div>
    </details>
  );
}
export function SpaceWeatherPanel() {
  const [data, setData] = useState<{
      data: Record<
        string,
        { records: Record<string, string | number | null>[] }
      >;
      provenance: { status: string }[];
    } | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const refresh = () =>
      request<{
        data: Record<
          string,
          { records: Record<string, string | number | null>[] }
        >;
        provenance: { status: string }[];
      }>("/api/v2/space-weather/history")
        .then((v) => {
          if (active) setData(v);
        })
        .catch(() => {
          if (active) setError("Space weather unavailable");
        });
    void refresh();
    const timer = setInterval(() => void refresh(), 30000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  const kp = data?.data?.kp?.records?.at(-1),
    wind = data?.data?.solar_wind?.records?.at(-1),
    storm = data?.data?.geomagnetic?.records?.at(-1);
  return (
    <section className="layer-detail">
      <strong>NOAA space weather</strong>
      <p>
        Kp: {kp?.Kp ?? kp?.kp ?? "Not loaded"} · {kp?.time_tag ?? ""} UTC
      </p>
      <p>
        Geomagnetic:{" "}
        {storm ? "G" + storm.scale + " · " + storm.text : "Not loaded"}
      </p>
      {storm && <small>{storm.time_tag} · NOAA reported state</small>}
      <p>Solar wind: {wind?.speed ?? "Not loaded"} km/s</p>
      {data?.data?.alerts?.records?.slice(0, 3).map((a, i) => (
        <details key={i}>
          <summary>
            {a.product_id} · {a.issue_datetime} UTC
          </summary>
          <p style={{ whiteSpace: "pre-wrap" }}>{a.message}</p>
        </details>
      ))}
      <small>
        Global/upstream indices, not a ground location.{" "}
        {data?.provenance?.[0]?.status}. {error}
      </small>
    </section>
  );
}
