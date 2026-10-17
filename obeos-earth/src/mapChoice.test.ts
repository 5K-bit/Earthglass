import { describe, expect, it } from "vitest";
import { needsLocalReferenceLabels, type MapStatus } from "./mapChoice";

describe("offline reference visibility", () => {
  it("keeps labels in offline mode", () => {
    expect(needsLocalReferenceLabels({ mode: "offline", state: "offline", message: "" })).toBe(true);
  });
  it.each(["satellite", "streets"] as const)("restores labels on %s failure and removes them on recovery", (mode) => {
    const status: MapStatus = { mode, state: "fallback", message: "" };
    expect(needsLocalReferenceLabels(status)).toBe(true);
    expect(needsLocalReferenceLabels({ ...status, state: "ready" })).toBe(false);
    expect(needsLocalReferenceLabels({ ...status, state: "loading" })).toBe(false);
  });
});
