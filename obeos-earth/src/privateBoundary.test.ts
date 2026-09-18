import { it, expect, vi, afterEach } from "vitest";
import { request, setPrivateViewerToken } from "./controlApi";
import { RenderGovernor } from "./renderGovernor";
afterEach(() => {
  setPrivateViewerToken(null);
  vi.unstubAllGlobals();
});
it("sends a private viewer credential only to exact private Presence paths", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal("fetch", fetcher);
  setPrivateViewerToken("fixture-private-token");
  await request("/private/v2/presence");
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBe(
    "Bearer fixture-private-token",
  );
  for (const path of [
    "/api/v2/observations",
    "/private/v2/presence-public",
    "https://example.org/private/v2/presence",
  ]) {
    await request(path);
    expect(fetcher.mock.calls.at(-1)![1].headers.Authorization).toBeUndefined();
  }
  setPrivateViewerToken(null);
  await request("/private/v2/presence");
  expect(fetcher.mock.calls.at(-1)![1].headers.Authorization).toBeUndefined();
});
it("unchanged render holds do not keep requesting frames", () => {
  vi.stubGlobal("window", {});
  vi.stubGlobal("document", {
    hidden: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const render = vi.fn();
  const v = {
    isDestroyed: () => false,
    scene: {
      requestRender: render,
      postRender: { addEventListener: () => () => {} },
    },
  };
  const governor = new RenderGovernor(v as never);
  render.mockClear();
  governor.hold("motion", false);
  expect(render).not.toHaveBeenCalled();
  governor.hold("motion", true);
  render.mockClear();
  governor.hold("motion", true);
  expect(render).not.toHaveBeenCalled();
  governor.destroy();
});
