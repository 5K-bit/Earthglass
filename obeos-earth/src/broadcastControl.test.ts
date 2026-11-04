import { describe, expect, it } from "vitest";
import { controlLink, nextProgram, parseProgram } from "./broadcastControl";

const scenes = ["nyc", "mia"];
const fields = ["radar", "temperature"];
const good = { scene: "mia", field: "radar", revision: 3, updated_at: "2026-01-01T00:00:00Z" };

describe("parseProgram", () => {
  it("accepts a valid state", () => {
    expect(parseProgram(good, scenes, fields)).toEqual({ scene: "mia", field: "radar", revision: 3, updatedAt: "2026-01-01T00:00:00Z" });
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
