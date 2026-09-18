import { useEffect, useState } from "react";
import { request } from "./controlApi";
type Alert = {
  id: string;
  header: string;
  description: string;
  provider: string;
  source_time: string;
};
export function MobilityPanel() {
  const [alerts, setAlerts] = useState<Alert[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [imports, setImports] = useState<
      {
        agency: string;
        imported_at: string;
        route_count: number;
        stop_count: number;
      }[]
    >([]);
  const [agency, setAgency] = useState("mta"),
    [source, setSource] = useState("https://www.mta.info/developers"),
    [attribution, setAttribution] = useState(
      "Data obtained from MTA; stored locally by OBEOS",
    );
  const refresh = () => {
    void request<{ data: Alert[] }>("/api/v2/mobility/transit/alerts")
      .then((v) => setAlerts(v.data))
      .catch(() => {});
    void request<{ data: typeof imports }>("/api/v2/mobility/transit/imports")
      .then((v) => setImports(v.data))
      .catch(() => {});
  };
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 60000);
    return () => clearInterval(timer);
  }, []);
  const importFile = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      if (file.size > 12 * 1024 * 1024)
        throw new Error(
          "The desktop importer accepts ZIP files up to 12 MiB. Use the local import command for a larger archive.",
        );
      await request(
        "/api/v2/mobility/transit/import?" +
          new URLSearchParams({ agency, source_url: source, attribution }),
        {
          method: "POST",
          headers: { "Content-Type": "application/zip" },
          body: await file.arrayBuffer(),
        },
      );
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="layer-row">
      <summary>
        Transit desk <small> · routes, stops and alerts</small>
      </summary>
      <div className="layer-detail">
        <p>
          Enable an MTA feed below for service updates. Reports without vehicle
          coordinates stay off the map. Marker motion blends recent reported
          positions for two seconds; it never predicts the next stop.
        </p>
        <p>
          Data obtained from MTA is stored by OBEOS. When older than one minute
          it may no longer be real time. Coverage, accuracy and timeliness are
          not guaranteed.
        </p>
        {alerts.slice(0, 30).map((a) => (
          <details key={a.provider + a.id}>
            <summary>{a.header}</summary>
            <p>{a.description}</p>
            <small>
              {a.source_time} · {a.provider}
            </small>
          </details>
        ))}
        {!alerts.length && <p>No locally cached service alerts.</p>}
        <details>
          <summary>Import routes for offline use</summary>
          <p>
            Use a public GTFS ZIP. Importing replaces the selected agency’s
            route and stop catalog. Live vehicle positions require an online
            feed.
          </p>
          <label>
            Agency ID
            <input
              value={agency}
              onChange={(e) => setAgency(e.target.value)}
              maxLength={40}
            />
          </label>
          <label>
            Official source URL
            <input
              type="url"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
          </label>
          <label>
            Attribution
            <input
              value={attribution}
              onChange={(e) => setAttribution(e.target.value)}
            />
          </label>
          <input
            aria-label="Import public GTFS ZIP"
            type="file"
            accept=".zip,application/zip"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importFile(file);
              e.target.value = "";
            }}
          />
          {imports.map((v) => (
            <p key={v.agency}>
              {v.agency}: {v.route_count} routes, {v.stop_count} stops ·{" "}
              {new Date(v.imported_at).toLocaleDateString()}
            </p>
          ))}
        </details>
        {busy && <p role="status">Importing local transit…</p>}
        {error && <p role="status">{error}</p>}
      </div>
    </details>
  );
}
