import { afterEach, expect, it, vi } from "vitest";
import { RenderGovernor } from "./renderGovernor";
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
it("counts active stalls but excludes time spent hidden or idle", () => {
  vi.useFakeTimers();
  let clock = 0, frame = () => {};
  const listeners = new Map<string, () => void>();
  const doc = { hidden: false, addEventListener:(k:string,fn:()=>void)=>listeners.set(k,fn), removeEventListener:vi.fn() };
  vi.stubGlobal("document", doc);
  vi.stubGlobal("window", {});
  vi.stubGlobal("performance", { now: () => clock });
  const viewer = {
    resolutionScale:1, targetFrameRate:0, useDefaultRenderLoop:true,
    canvas:{width:1920,height:1080}, isDestroyed:()=>false,
    scene:{maximumRenderTimeChange:0, requestRenderMode:true, requestRender:vi.fn(),
      postRender:{addEventListener:(fn:()=>void)=>{frame=fn;return vi.fn();}}},
  };
  const governor = new RenderGovernor(viewer as never);
  governor.hold("orbit",true); frame();
  for(let i=0;i<90;i++){clock+=i<6?1500:33;frame();}
  expect(window.earthMetrics?.frameP95Ms).toBe(1500);
  expect(window.earthMetrics?.frameSampledIntervals).toBe(90);
  doc.hidden=true; listeners.get("visibilitychange")!();
  clock+=60000; doc.hidden=false; listeners.get("visibilitychange")!(); frame();
  for(let i=0;i<90;i++){clock+=33;frame();}
  expect(window.earthMetrics?.frameP95Ms).toBe(33);
  expect(window.earthMetrics?.worstFrameP95Ms).toBe(1500);
  expect(window.earthMetrics?.frameWindowCount).toBe(2);
  governor.hold("orbit",false); vi.advanceTimersByTime(401);
  expect(window.earthMetrics?.renderMode).toBe("idle");
  expect(window.earthMetrics?.resolution).toBe(1);
  clock+=50000; frame();
  expect(window.earthMetrics?.frameSampledIntervals).toBe(180);
  governor.destroy();
});
