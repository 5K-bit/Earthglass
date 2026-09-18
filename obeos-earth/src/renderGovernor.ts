/** Explicit rendering with owned continuous modes, adaptive resolution and hidden-page suspension. */
import type { Viewer } from "cesium";
export class RenderGovernor {
  detailBudget = 1200;
  onBudgetChange?: () => void;
  private holds = new Set<string>();
  private visibility = () => this.apply();
  private lastFrame: number | null = null;
  private sampling = false;
  private sampledIntervals = 0;
  private sampleWindows = 0;
  private worstP95 = 0;
  private adaptiveResolution = 0.85;
  private idleTimer: ReturnType<typeof setTimeout> | undefined;
  private samples: number[] = [];
  private removeFrame: () => void;
  constructor(private viewer: Viewer) {
    viewer.targetFrameRate = 30;
    viewer.resolutionScale = 0.85;
    viewer.scene.maximumRenderTimeChange = Infinity;
    document.addEventListener("visibilitychange", this.visibility);
    this.removeFrame = viewer.scene.postRender.addEventListener(() => {
      const now = performance.now();
      if (this.sampling && this.lastFrame !== null) {
        // Include long active stalls. Idle/hidden time is excluded by resetting at mode changes.
        this.samples.push(now - this.lastFrame);
        this.sampledIntervals++;
      }
      this.lastFrame = this.sampling ? now : null;
      if (this.samples.length >= 90) {
        const sorted = [...this.samples].sort((a, b) => a - b);
        const p95 = sorted[Math.floor(sorted.length * 0.95)];
        this.worstP95 = Math.max(this.worstP95, p95);
        this.sampleWindows++;
        const budget = this.detailBudget;
        if (p95 > 45) this.detailBudget = Math.max(200, Math.floor(this.detailBudget * 0.7));
        else if (p95 < 35) this.detailBudget = Math.min(2500, this.detailBudget + 100);
        if (budget !== this.detailBudget) this.onBudgetChange?.();
        if (p95 > 50) this.adaptiveResolution = Math.max(0.5, this.adaptiveResolution - 0.1);
        else if (p95 < 36) this.adaptiveResolution = Math.min(1, this.adaptiveResolution + 0.05);
        if (this.sampling) viewer.resolutionScale = this.adaptiveResolution;
        window.earthMetrics = {
          ...window.earthMetrics,
          frameP95Ms: p95,
          frameP50Ms: sorted[Math.floor(sorted.length * 0.5)],
          worstFrameP95Ms: this.worstP95,
        };
        this.samples = [];
      }
      this.publish();
    });
    this.apply();
  }
  private publish() {
    window.earthMetrics = {
      ...window.earthMetrics,
      resolution: this.viewer.resolutionScale,
      targetFPS: 30,
      canvasWidth: this.viewer.canvas?.width ?? 0,
      canvasHeight: this.viewer.canvas?.height ?? 0,
      detailBudget: this.detailBudget,
      renderMode: document.hidden ? "hidden" : this.sampling ? "continuous" : "idle",
      renderOwners: [...this.holds].sort().join(","),
      frameSampledIntervals: this.sampledIntervals,
      frameWindowCount: this.sampleWindows,
    };
  }
  hold(owner: string, active: boolean) {
    if (this.holds.has(owner) === active) return;
    if (active) this.holds.add(owner);
    else this.holds.delete(owner);
    this.apply();
  }
  request() {
    if (!document.hidden && !this.viewer.isDestroyed()) this.viewer.scene.requestRender();
  }
  private apply() {
    if (this.viewer.isDestroyed()) return;
    const sampling = this.holds.size > 0 && !document.hidden;
    if (sampling !== this.sampling) {
      this.lastFrame = null;
      this.samples = [];
      this.sampling = sampling;
    }
    clearTimeout(this.idleTimer);
    if (this.holds.size) this.viewer.resolutionScale = this.adaptiveResolution;
    else if (!document.hidden) this.idleTimer = setTimeout(() => {
      if (this.viewer.isDestroyed() || this.holds.size || document.hidden) return;
      this.viewer.resolutionScale = 1;
      this.publish();
      this.request();
    }, 400);
    this.viewer.useDefaultRenderLoop = !document.hidden;
    this.viewer.scene.requestRenderMode = this.holds.size === 0 || document.hidden;
    this.publish();
    this.request();
  }
  destroy() {
    clearTimeout(this.idleTimer);
    document.removeEventListener("visibilitychange", this.visibility);
    this.removeFrame();
    this.holds.clear();
  }
}
