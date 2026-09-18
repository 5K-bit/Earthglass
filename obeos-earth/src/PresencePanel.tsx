import { useEffect, useState } from "react";
import { request } from "./controlApi";
import type { PrivateDevice, PrivatePosition } from "./presenceRenderer";
import type { SceneController } from "./sceneController";
const base = "/private/v2/presence";
type Settings = {
  enabled: boolean;
  role: "owner" | "viewer";
  live_seconds: number;
  recent_seconds: number;
  stale_seconds: number;
};
export function PresencePanel({
  controller,
  at,
}: {
  controller: () => SceneController | null;
  at: string | null;
}) {
  const [visible, setVisible] = useState(false),
    [accuracy, setAccuracy] = useState(true),
    [devices, setDevices] = useState<PrivateDevice[]>([]),
    [selected, setSelected] = useState(""),
    [error, setError] = useState(""),
    [settings, setSettings] = useState<Settings | null>(null),
    [trailMinutes, setTrailMinutes] = useState(0),
    [revision, setRevision] = useState(0);
  const [label, setLabel] = useState(""),
    [deviceId, setDeviceId] = useState(""),
    [traccarId, setTraccarId] = useState(""),
    [secret, setSecret] = useState(""),
    [viewerName, setViewerName] = useState(""),
    [viewHistory, setViewHistory] = useState(false),
    [viewBattery, setViewBattery] = useState(false);
  const [grants, setGrants] = useState<
    { id: string; label: string; expires: number }[]
  >([]);
  const device = devices.find((d) => d.device_id === selected);
  const action = async (path: string, method: string, body?: unknown) => {
    try {
      setError("");
      const value = await request<Record<string, unknown>>(base + path, {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      setRevision((v) => v + 1);
      return value;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  };
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const [result, config] = await Promise.all([
          request<{ data: PrivateDevice[] }>(
            base + (at ? "?at=" + encodeURIComponent(at) : ""),
          ),
          request<Settings>(base + "/settings"),
        ]);
        if (!active) return;
        setDevices(result.data);
        setSettings(config);
        controller()?.onPrivateSelection(setSelected);
        controller()?.setPrivatePresence(visible ? result.data : [], accuracy);
        if (
          visible &&
          selected &&
          trailMinutes > 0 &&
          result.data.find((d) => d.device_id === selected)?.permissions.history
        ) {
          const end = at ? new Date(at) : new Date(),
            start = new Date(end.getTime() - trailMinutes * 60000);
          const trail = await request<{
            data: PrivatePosition[];
            next_cursor: number | null;
          }>(
            base +
              "/" +
              encodeURIComponent(selected) +
              "/trail?start=" +
              encodeURIComponent(start.toISOString()) +
              "&end=" +
              encodeURIComponent(end.toISOString()) +
              "&limit=2000",
          );
          if (active) {
            controller()?.setPrivateTrail(trail.data);
            if (trail.next_cursor)
              setError(
                "Trail is limited to 2,000 points. Select a shorter time range.",
              );
          }
        } else controller()?.setPrivateTrail([]);
      } catch (e) {
        if (active) {
          setDevices([]);
          setSettings(null);
          setGrants([]);
          controller()?.setPrivatePresence([], accuracy);
          controller()?.setPrivateTrail([]);
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [controller, at, visible, accuracy, selected, trailMinutes, revision]);
  useEffect(
    () => () => {
      controller()?.clearPrivatePresence();
      controller()?.onPrivateSelection();
    },
    [controller],
  );
  useEffect(() => {
    let active = true;
    void request<{ data: typeof grants }>(base + "/viewers")
      .then((v) => {
        if (active) setGrants(v.data);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [revision]);
  return (
    <details className="layer-row">
      <summary>
        Private Presence{" "}
        <small> · {settings?.enabled ? "configured" : "setup deferred"}</small>
      </summary>
      <div className="layer-detail">
        <p>
          Cloud Node, Tailscale and phone enrollment will be configured later.
          Tracking starts disabled.
        </p>
        <label>
          <input
            type="checkbox"
            checked={visible}
            onChange={(e) => setVisible(e.target.checked)}
          />{" "}
          Show authorized devices
        </label>
        <label>
          <input
            type="checkbox"
            checked={accuracy}
            onChange={(e) => setAccuracy(e.target.checked)}
          />{" "}
          Accuracy circle
        </label>
        <select
          aria-label="Private device"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          <option value="">Select a device</option>
          {devices.map((d) => (
            <option key={d.device_id} value={d.device_id}>
              {d.label} · {d.status}
            </option>
          ))}
        </select>
        {device && (
          <section>
            <strong>{device.label}</strong>
            <p>
              {device.status} ·{" "}
              {device.position
                ? new Date(device.position.recorded_at).toLocaleString()
                : "No position received"}
            </p>
            <p>
              Accuracy {device.position?.accuracy_m ?? "unknown"} m · Speed{" "}
              {device.position?.speed_mps ?? "unknown"} m/s · Battery{" "}
              {device.position?.battery_percent ?? "not shared"}%
            </p>
            <p>
              Heading{" "}
              {device.position?.heading_deg == null
                ? "unknown"
                : device.position.heading_deg.toFixed(0) + "°"}{" "}
              · Traccar
            </p>
            <div className="button-row">
              {[
                ["Close", 300],
                ["City", 8000],
                ["Regional", 60000],
              ].map(([name, distance]) => (
                <button
                  key={name}
                  disabled={!visible || !device.position}
                  onClick={() =>
                    controller()?.followPrivate(selected, Number(distance))
                  }
                >
                  Follow {name}
                </button>
              ))}
              <button onClick={() => controller()?.stopPrivateFollow()}>
                Stop follow
              </button>
            </div>
            <label>
              Trail
              <select
                value={trailMinutes}
                disabled={!device.permissions.history}
                onChange={(e) => setTrailMinutes(Number(e.target.value))}
              >
                {[
                  [0, "Off"],
                  [15, "15 minutes"],
                  [60, "One hour"],
                  [1440, "24 hours"],
                  ...(![0, 15, 60, 1440].includes(trailMinutes)
                    ? [[trailMinutes, "Custom"]]
                    : []),
                ].map(([value, name]) => (
                  <option key={value} value={value}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Custom trail (minutes)
              <input
                type="number"
                min={0}
                max={10080}
                step={1}
                value={trailMinutes}
                disabled={!device.permissions.history}
                onChange={(e) =>
                  setTrailMinutes(
                    Math.max(
                      0,
                      Math.min(10080, Math.floor(Number(e.target.value))),
                    ),
                  )
                }
              />
            </label>
            <p>
              History follows the Earth timeline when permission is granted.
            </p>
          </section>
        )}
        <details hidden={settings?.role !== "owner"}>
          <summary>Owner settings</summary>
          <label>
            <input
              type="checkbox"
              checked={settings?.enabled ?? false}
              onChange={(e) => {
                if (settings)
                  void action("/settings", "PATCH", {
                    live_seconds: settings.live_seconds,
                    recent_seconds: settings.recent_seconds,
                    stale_seconds: settings.stale_seconds,
                    enabled: e.target.checked,
                  });
              }}
            />{" "}
            Enable private position ingestion
          </label>
          {device && (
            <>
              <label>
                <input
                  type="checkbox"
                  checked={device.tracking_enabled}
                  onChange={(e) =>
                    void action(
                      "/devices/" + encodeURIComponent(selected),
                      "PATCH",
                      { tracking_enabled: e.target.checked },
                    )
                  }
                />{" "}
                Authorize this device to report
              </label>
              <label>
                Retention
                <select
                  value={device.retention_days}
                  onChange={(e) =>
                    void action(
                      "/devices/" + encodeURIComponent(selected),
                      "PATCH",
                      { retention_days: Number(e.target.value) },
                    )
                  }
                >
                  {[
                    [0, "History disabled"],
                    [1, "24 hours"],
                    [7, "7 days"],
                    [30, "30 days"],
                    [90, "90 days"],
                    [365, "One year"],
                    ...(![0, 1, 7, 30, 90, 365].includes(device.retention_days)
                      ? [[device.retention_days, "Custom"]]
                      : []),
                  ].map(([v, n]) => (
                    <option key={v} value={v}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <form
                key={selected + ":" + device.retention_days}
                onSubmit={(e) => {
                  e.preventDefault();
                  const value = Number(
                    new FormData(e.currentTarget).get("days"),
                  );
                  void action(
                    "/devices/" + encodeURIComponent(selected),
                    "PATCH",
                    { retention_days: value },
                  );
                }}
              >
                <label>
                  Custom retention (days)
                  <input
                    name="days"
                    type="number"
                    min={0}
                    max={3650}
                    step={1}
                    required
                    defaultValue={device.retention_days}
                  />
                </label>
                <button type="submit">Apply retention</button>
              </form>
              <button
                onClick={() =>
                  void action(
                    "/devices/" + encodeURIComponent(selected) + "/rotate",
                    "POST",
                  ).then((v) => {
                    if (v?.token) setSecret(String(v.token));
                  })
                }
              >
                Rotate device credential
              </button>
              <button
                onClick={() => {
                  if (
                    window.confirm(
                      "Delete this device and its private history?",
                    )
                  )
                    void action(
                      "/devices/" + encodeURIComponent(selected),
                      "DELETE",
                    );
                }}
              >
                Remove device and history
              </button>
            </>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action("/devices", "POST", {
                device_id: deviceId,
                label,
                traccar_id: traccarId,
                tracking_enabled: false,
                retention_days: 30,
              }).then((v) => {
                if (v?.token) {
                  setSecret(String(v.token));
                  setSelected(deviceId);
                }
              });
            }}
          >
            <input
              aria-label="Device label"
              placeholder="Device label"
              required
              maxLength={100}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            <input
              aria-label="Device ID"
              placeholder="device-id"
              required
              pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}"
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
            />
            <input
              aria-label="Traccar device ID"
              placeholder="Traccar numeric device ID"
              required
              value={traccarId}
              onChange={(e) => setTraccarId(e.target.value)}
            />
            <button type="submit">Register disabled device</button>
          </form>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action("/viewers", "POST", {
                label: viewerName,
                devices: [selected],
                history: viewHistory,
                battery: viewBattery,
                expires_days: 30,
              }).then((v) => {
                if (v?.token) setSecret(String(v.token));
              });
            }}
          >
            <input
              aria-label="Viewer label"
              placeholder="Viewer name"
              required
              value={viewerName}
              onChange={(e) => setViewerName(e.target.value)}
            />
            <label>
              <input
                type="checkbox"
                checked={viewHistory}
                onChange={(e) => setViewHistory(e.target.checked)}
              />{" "}
              Share history
            </label>
            <label>
              <input
                type="checkbox"
                checked={viewBattery}
                onChange={(e) => setViewBattery(e.target.checked)}
              />{" "}
              Share battery
            </label>
            <button disabled={!selected} type="submit">
              Grant selected device · 30 days
            </button>
          </form>
          {grants.map((g) => (
            <p key={g.id}>
              {g.label}
              <button onClick={() => void action("/viewers/" + g.id, "DELETE")}>
                Revoke
              </button>
            </p>
          ))}
          {secret && (
            <div>
              <p>
                One-time credential. Store it securely for your later
                configuration.
              </p>
              <input
                aria-label="New private credential"
                type="password"
                readOnly
                value={secret}
                onFocus={(e) => e.target.select()}
              />
              <button onClick={() => setSecret("")}>Dismiss</button>
            </div>
          )}
        </details>
        {error && <p role="status">{error}</p>}
      </div>
    </details>
  );
}
