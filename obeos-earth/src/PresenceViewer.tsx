import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "./styles.css";
import { PresencePanel } from "./PresencePanel";
import { request, setPrivateViewerToken } from "./controlApi";
import type { SceneController } from "./sceneController";

function PrivateViewer() {
  const canvas = useRef<HTMLDivElement>(null),
    controller = useRef<SceneController | null>(null);
  const getController = useCallback(() => controller.current, []);
  const [ready, setReady] = useState(false),
    [signedIn, setSignedIn] = useState(false);
  const [token, setToken] = useState(""),
    [error, setError] = useState(""),
    [at, setAt] = useState("");
  useEffect(() => {
    let active = true;
    void import("./sceneController")
      .then(({ SceneController }) => {
        if (!active || !canvas.current) return;
        controller.current = new SceneController(
          canvas.current,
          () => {},
          () => {},
          setError,
          () => {},
        );
        setReady(true);
      })
      .catch(() =>
        setError("Renderer unavailable. Reload the private viewer."),
      );
    return () => {
      active = false;
      controller.current?.destroy();
      controller.current = null;
      setPrivateViewerToken(null);
    };
  }, []);
  const signIn = async () => {
    setError("");
    setPrivateViewerToken(token.trim());
    try {
      await request("/private/v2/presence/settings");
      setSignedIn(true);
      setToken("");
    } catch {
      setPrivateViewerToken(null);
      setError(
        "Access was not granted. Check the private network and unexpired viewer credential.",
      );
    }
  };
  return (
    <main
      style={{
        height: "100dvh",
        display: "grid",
        gridTemplateColumns: "minmax(280px, 350px) 1fr",
      }}
    >
      <aside className="panel" style={{ padding: 16, overflowY: "auto" }}>
        <h1>Private Presence</h1>
        <p>Authorized devices · OBEOS</p>
        {!signedIn ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void signIn();
            }}
          >
            <label>
              Viewer credential
              <input
                type="password"
                autoComplete="off"
                required
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </label>
            <button disabled={!ready} type="submit">
              Open private view
            </button>
            <p>The credential stays in memory until sign-out or page close.</p>
          </form>
        ) : (
          <>
            <button
              onClick={() => {
                setSignedIn(false);
                setPrivateViewerToken(null);
                controller.current?.clearPrivatePresence();
                setAt("");
              }}
            >
              Sign out
            </button>
            <PresencePanel
              controller={getController}
              at={at ? new Date(at + "Z").toISOString() : null}
            />
            <label>
              History time (UTC)
              <input
                type="datetime-local"
                value={at}
                onChange={(e) => setAt(e.target.value)}
              />
            </label>
            <button onClick={() => setAt("")}>Return to current</button>
            <small>
              History requires a grant. The bundled overview has limited street
              detail. No location is sent to a public map service.
            </small>
          </>
        )}
        {error && <p role="alert">{error}</p>}
      </aside>
      <div
        ref={canvas}
        style={{ minWidth: 0, height: "100%" }}
        aria-label="Private device globe"
      />
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<PrivateViewer />);
