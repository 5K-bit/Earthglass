import { describe, expect, it } from "vitest";
import { controlLink, nextProgram, parseProgram, parseRecovery } from "./broadcastControl";

const scenes = ["nyc", "mia"];
const fields = ["radar", "temperature"];
const good = { scene: "mia", field: "radar", revision: 3, updated_at: "2026-01-01T00:00:00Z" };

describe("parseRecovery", () => {
  it("reports a startup without the previously committed shot, and clears once the server stops reporting it", () => {
    expect(parseRecovery({ revision: 0, persistence: { ok: true, recovered_from: "ValueError: bad json" } })).toBe("ValueError: bad json");
    expect(parseRecovery({ revision: 1, persistence: { ok: true, recovered_from: null } })).toBeNull();
    expect(parseRecovery({})).toBeNull();
    expect(parseRecovery(null)).toBeNull();
  });
});

describe("parseProgram", () => {
  it("accepts a valid state", () => {
    expect(parseProgram(good, scenes, fields)).toEqual({ scene: "mia", field: "radar", revision: 3, updatedAt: "2026-01-01T00:00:00Z", persistenceError: null });
    expect(parseProgram({ ...good, persistence: { ok: false, error: "OSError: disk full" } }, scenes, fields)?.persistenceError).toBe("OSError: disk full");
  });
  it("rejects unset, unknown and malformed states", () => {
    expect(parseProgram({ ...good, scene: null, revision: 0 }, scenes, fields)).toBeNull();
    expect(parseProgram({ ...good, scene: "xyz" }, scenes, fields)).toBeNull();
    expect(parseProgram({ ...good, field: "lava" }, scenes, fields)).toBeNull();
    expect(parseProgram({ ...good, revision: 1.5 }, scenes, fields)).toBeNull();
    expect(parseProgram("nope", scenes, fields)).toBeNull();
  });
});

describe("nextProgram", () => {
  const a = parseProgram(good, scenes, fields)!;
  it("takes a newer revision", () => {
    const b = { ...a, revision: 4, scene: "nyc" };
    expect(nextProgram(a, b)).toBe(b);
    expect(nextProgram(null, a)).toBe(a);
  });
  it("ignores stale, equal or invalid replies", () => {
    expect(nextProgram(a, { ...a, revision: 2, scene: "nyc" })).toBe(a);
    expect(nextProgram(a, { ...a })).toBe(a);
    expect(nextProgram(a, null)).toBe(a);
  });
});

describe("controlLink", () => {
  it("reports never, ok and lost", () => {
    expect(controlLink(null, 10_000)).toBe("never");
    expect(controlLink(9_000, 10_000)).toBe("ok");
    expect(controlLink(1_000, 10_000)).toBe("lost");
  });
});
