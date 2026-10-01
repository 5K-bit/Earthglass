import { useEffect, useRef, useState } from "react";
import { request } from "./controlApi";
import {
  turnsFrom,
  noticeFrom,
  sessionFrom,
  isSilent,
  type ChatTurn,
} from "./chatTurns";

/** Talk to D.A.I.S.E. without leaving the globe.
 *
 *  Distinct from the D.A.I.S.E. panel beside it: that one explains the current
 *  scene and stands alone, while this carries session identity, so turns join the
 *  operator's shared conversation and show up on the HUD and the classic shell too.
 */
export function ChatPanel({ onClose }: { onClose: () => void }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const session = useRef("");
  const log = useRef<HTMLDivElement | null>(null);
  const live = useRef(true);
  useEffect(() => () => void (live.current = false), []);

  // Follow the newest turn. Scrolling the node directly keeps a long reply from
  // re-rendering the list, which the render governor would read as a globe stall.
  useEffect(() => {
    const node = log.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [turns]);

  async function send() {
    const message = draft.trim();
    if (!message || busy) return;
    setBusy(true);
    setNotice("");
    // Shown immediately so the panel is not silent while a local model thinks.
    setTurns((prior) => [
      ...prior,
      {
        id: `pending-${Date.now()}`,
        role: "user",
        text: message,
        agent: "operator",
      },
    ]);
    setDraft("");
    try {
      const reply = await request<Parameters<typeof turnsFrom>[0]>(
        "/api/chat",
        {
          method: "POST",
          body: JSON.stringify({
            message,
            session_id: session.current || undefined,
            analysis_mode: "standard",
          }),
          // A local model on a CPU-only machine needs far longer than the 15s
          // default; the scene explainer alongside this uses 45s for the same reason.
          signal: AbortSignal.timeout(180000),
        },
      );
      if (!live.current) return;
      session.current = sessionFrom(reply, session.current);
      const history = turnsFrom(reply);
      // Server history is authoritative once it arrives, which also replaces the
      // optimistic turn rather than duplicating it.
      if (history.length) setTurns(history);
      setNotice(
        noticeFrom(reply) ||
          (isSilent(reply) ? "That turn produced no reply." : ""),
      );
    } catch (error) {
      if (!live.current) return;
      setNotice(
        error instanceof Error && error.name === "TimeoutError"
          ? "The local model did not answer in time. It may still be loading."
          : "Chat is unreachable. Check that the local model service is running.",
      );
    } finally {
      if (live.current) setBusy(false);
    }
  }

  return (
    <aside className="chat panel">
      <div className="panel-title">
        <div>
          <small>OPERATOR CHAT</small>
          <h2>D.A.I.S.E.</h2>
        </div>
        <button onClick={onClose} aria-label="Close chat">
          ×
        </button>
      </div>
      <div className="chat-log" ref={log}>
        {!turns.length && (
          <p className="empty">
            Shares the operator session with the HUD and the classic workspace,
            so this conversation continues wherever you pick it up.
          </p>
        )}
        {turns.map((turn) => (
          <article key={turn.id} className={"chat-turn " + turn.role}>
            <small>{turn.role === "user" ? "You" : turn.agent}</small>
            <p>{turn.text}</p>
          </article>
        ))}
      </div>
      {notice && <p role="status">{notice}</p>}
      <textarea
        className="wide"
        aria-label="Message for DAISE"
        placeholder="Ask about this view, or anything else…"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void send();
          }
        }}
      />
      <button
        className="primary wide"
        disabled={busy || !draft.trim()}
        onClick={() => void send()}
      >
        {busy ? "Thinking…" : "Send"}
      </button>
    </aside>
  );
}
