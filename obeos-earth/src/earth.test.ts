import { describe, it, expect, vi, afterEach } from "vitest";
import { reconcile } from "./contactIndex";
import { observationQuery } from "./controlApi";
import { RenderGovernor } from "./renderGovernor";
import type { Observation } from "./contracts";

const value = (id: string, second = 0) =>
  ({
    entity_id: id,
    observation_id: id + second,
    observed_at: new Date(1000 * second).toISOString(),
  }) as unknown as Observation;
afterEach(() => vi.unstubAllGlobals());
describe("contact update lifecycle", () => {
  it("keeps a selected contact during live updates and rejects older motion", () => {
    const contacts = new Map([
      ["selected", value("selected", 5)],
      ["other", value("other")],
    ]);
    reconcile(contacts, [value("other", 2)], true, ["selected"]);
    reconcile(contacts, [value("selected", 1)]);
    expect(contacts.get("selected")?.observed_at).toBe(
      value("selected", 5).observed_at,
    );
    expect(contacts.get("other")?.observed_at).toBe(
      value("other", 2).observed_at,
    );
  });
  it("replay removes future contacts and accepts an earlier time slice", () => {
    const contacts = new Map([
      ["future", value("future", 9)],
      ["same", value("same", 9)],
    ]);
    reconcile(contacts, [value("same", 2)], true);
    expect([...contacts.keys()]).toEqual(["same"]);
    expect(contacts.get("same")?.observed_at).toBe(
      value("same", 2).observed_at,
    );
  });
  it("bounds a high volume stream while preserving selection", () => {
    const contacts = new Map<string, Observation>();
    reconcile(
      contacts,
      Array.from({ length: 10000 }, (_, i) => value(String(i))),
      false,
      ["0"],
      2500,
    );
    expect(contacts.size).toBe(2500);
    expect(contacts.has("0")).toBe(true);
  });
  it("carries the snapshot boundary and date-line viewport in queries", () => {
    const url = observationQuery(
      { west: 170, east: -170, south: -10, north: 10 },
      null,
      2000,
      123,
    );
    expect(url).toContain("snapshot_rowid=123");
    expect(url).toContain("east=-170");
  });
});
it("rendering remains continuous until every owner releases and pauses while hidden", () => {
  vi.useFakeTimers();
  let frame = () => {};
  const listeners = new Map<string, () => void>();
  const documentMock = {
    hidden: false,
    addEventListener: (key: string, fn: () => void) => listeners.set(key, fn),
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal("document", documentMock);
  vi.stubGlobal("window", {});
  const remove = vi.fn();
  const viewer = {
    targetFrameRate: 0,
    resolutionScale: 1,
    useDefaultRenderLoop: true,
    isDestroyed: () => false,
    scene: {
      maximumRenderTimeChange: 0,
      requestRenderMode: true,
      requestRender: vi.fn(),
      postRender: {
        addEventListener: (fn: () => void) => {
          frame = fn;
          return remove;
        },
      },
    },
  };
  const governor = new RenderGovernor(viewer as never);
  governor.hold("orbit", true);
  governor.hold("follow", true);
  governor.hold("orbit", false);
  expect(viewer.scene.requestRenderMode).toBe(false);
  documentMock.hidden = true;
  listeners.get("visibilitychange")?.();
  expect(viewer.useDefaultRenderLoop).toBe(false);
  documentMock.hidden = false;
  listeners.get("visibilitychange")?.();
  frame();
  governor.hold("follow", false);
  expect(viewer.scene.requestRenderMode).toBe(true);
  vi.advanceTimersByTime(401);
  expect(viewer.resolutionScale).toBe(1);
  governor.hold("camera", true);
  expect(viewer.resolutionScale).toBe(0.85);
  governor.destroy();
  vi.useRealTimers();
  expect(remove).toHaveBeenCalled();
});

import { observationIsStale } from "./observationFreshness";
it("separates earthquake event age from live track freshness", () => {
  const now = Date.now();
  const old = new Date(now - 8 * 3600000).toISOString();
  const current = new Date(now).toISOString();
  const quake = {
    layer: "earthquakes",
    observed_at: old,
    received_at: current,
  } as Observation;
  expect(observationIsStale(quake, now)).toBe(false);
  expect(observationIsStale({ ...quake, layer: "aircraft" }, now)).toBe(true);
});
