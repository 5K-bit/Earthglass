import { describe, expect, it, vi } from "vitest";
import { restoreSceneContacts } from "./restoreSceneContacts";
import type { Observation } from "./contracts";
import type { ObservationPage, SceneState } from "./controlApi";
const point = (id: string) => ({ entity_id: id }) as Observation;
const page = (id: string) => ({ observations: [point(id)] }) as ObservationPage;
const scene = {
  selected_entity_id: "stop:selected", tracked_entity_id: "stop:selected",
  camera: { mode: "orbit", entity_id: "stop:camera" },
  timeline: { at: null }, enabled_layers: ["transit_stops"],
} as SceneState;

describe("scene contact restoration", () => {
  it("loads selected and tracked contacts outside the saved camera viewport, without duplicates", async () => {
    const fetch = vi.fn(async (path: string) =>
      page(new URL(path, "http://localhost").searchParams.get("entity_id")!));
    const restored = await restoreSceneContacts([point("visible")], scene, fetch);
    expect(restored.map((o) => o.entity_id)).toEqual(["visible", "stop:selected", "stop:camera"]);
    expect(fetch).toHaveBeenCalledTimes(2);
    for (const [path] of fetch.mock.calls) {
      const query = new URL(path, "http://localhost").searchParams;
      expect(query.get("limit")).toBe("1");
      expect(query.has("west")).toBe(false);
    }
  });
  it("uses the replay time and never fetches current data into a saved investigation", async () => {
    const fetch = vi.fn(async (_path: string) => ({ observations: [] }) as unknown as ObservationPage);
    const at = "2026-09-11T12:00:00Z";
    await restoreSceneContacts([], {...scene, timeline: {...scene.timeline, at}}, fetch);
    expect(new URL(fetch.mock.calls[0][0], "http://localhost").searchParams.get("at")).toBe(at);
    fetch.mockClear();
    await restoreSceneContacts([], {...scene, active_investigation_id:"saved"}, fetch);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("does not refetch visible contacts or substitute a different entity", async () => {
    const fetch = vi.fn(async () => page("unexpected"));
    const restored = await restoreSceneContacts([point("stop:selected")], scene, fetch);
    expect(restored.map((o) => o.entity_id)).toEqual(["stop:selected"]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
