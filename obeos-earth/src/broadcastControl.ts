// Pure logic for the server-held on-air state (see earthglass/control.py).

export type ProgramState = { scene: string; field: string; revision: number; updatedAt: string | null; persistenceError: string | null };

export const CONTROL_POLL_MS = 1000;
export const CONTROL_LINK_LOST_MS = 5000;

/** Validate a server reply against the shots/products this build knows; null if unusable. */
export function parseProgram(raw: unknown, scenes: readonly string[], fields: readonly string[]): ProgramState | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (typeof value.scene !== "string" || !scenes.includes(value.scene)) return null;
  if (typeof value.field !== "string" || !fields.includes(value.field)) return null;
  if (typeof value.revision !== "number" || !Number.isInteger(value.revision) || value.revision < 1) return null;
  const persistence = value.persistence as { ok?: unknown; error?: unknown } | undefined;
  const persistenceError = persistence && persistence.ok === false
    ? (typeof persistence.error === "string" ? persistence.error : "save failed")
    : null;
  return {
    scene: value.scene,
    field: value.field,
    revision: value.revision,
    updatedAt: typeof value.updated_at === "string" ? value.updated_at : null,
    persistenceError,
  };
}

/** Apply only a newer revision. A lower one means the server restarted or an old reply arrived late. */
export function nextProgram(current: ProgramState | null, incoming: ProgramState | null): ProgramState | null {
  if (!incoming) return current;
  if (current && incoming.revision <= current.revision) return current;
  return incoming;
}

export type ControlLink = "never" | "ok" | "lost";

export function controlLink(lastOkMs: number | null, nowMs: number): ControlLink {
  if (lastOkMs === null) return "never";
  return nowMs - lastOkMs > CONTROL_LINK_LOST_MS ? "lost" : "ok";
}
