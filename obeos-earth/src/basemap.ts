import {
  TileMapServiceImageryProvider,
  UrlTemplateImageryProvider,
  Credit,
} from "cesium";
import type { Viewer, ImageryLayer } from "cesium";
import type { Basemap, MapStatus } from "./mapChoice";
/** Keep the bundled overview under online tiles so failed requests never leave a blank globe. */
export class BasemapController {
  private epoch = 0;
  private overlay?: ImageryLayer;
  private reference?: ImageryLayer;
  private mode?: Exclude<Basemap, "auto">;
  /** Esri reference tiles stand in only while the local reference package is absent. */
  private referenceFallback = false;
  private cleanup = () => {};
  private base: Promise<void>;
  constructor(
    private viewer: Viewer,
    private changed: (status: MapStatus) => void,
  ) {
    this.base = TileMapServiceImageryProvider.fromUrl(
      "/cesium/Assets/Textures/NaturalEarthII",
      {
        credit: "Natural Earth · public domain; bundled with Cesium",
      },
    ).then((provider) => {
      if (!viewer.isDestroyed())
        viewer.imageryLayers.addImageryProvider(provider, 0);
    });
  }
  async set(mode: Exclude<Basemap, "auto">) {
    const epoch = ++this.epoch;
    this.mode = mode;
    this.cleanup();
    this.changed({
      mode,
      state: mode === "offline" ? "offline" : "loading",
      message:
        mode === "offline"
          ? "Offline overview · limited detail when zoomed in"
          : "Loading detailed map tiles…",
    });
    try {
      await this.base;
      if (epoch !== this.epoch || this.viewer.isDestroyed()) return;
      this.removeReference();
      if (this.overlay) this.viewer.imageryLayers.remove(this.overlay, true);
      this.overlay = undefined;
      if (mode === "offline") {
        this.viewer.scene.requestRender();
        return;
      }
      const provider = new UrlTemplateImageryProvider({
        url:
          mode === "satellite"
            ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            : "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        maximumLevel: 19,
        credit: new Credit(
          mode === "satellite"
            ? "Esri, Maxar, Earthstar Geographics and contributors"
            : '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
          true,
        ),
      });
      const layer = this.viewer.imageryLayers.addImageryProvider(provider);
      this.overlay = layer;
      layer.brightness = mode === "satellite" ? 0.9 : 0.8;
      layer.saturation = 0.65;
      this.applyReference();
      let retry: ReturnType<typeof setTimeout> | undefined;
      let failures = 0,
        settled = false;
      const fallback = () => {
        if (epoch !== this.epoch || this.viewer.isDestroyed()) return;
        settled = true;
        layer.show = false;
        if (this.reference) this.reference.show = false;
        clearTimeout(retry);
        retry = setTimeout(() => {
          void this.set(mode);
        }, 60000);
        this.changed({
          mode,
          state: "fallback",
          message:
            "Online imagery unavailable · local overview; retrying automatically",
        });
        this.viewer.scene.requestRender();
      };
      let deadline = setTimeout(() => {
        if (!settled) fallback();
      }, 25000);
      const removeError = provider.errorEvent.addEventListener(() => {
        if (++failures >= 3) fallback();
      });
      const removeProgress =
        this.viewer.scene.globe.tileLoadProgressEvent.addEventListener(
          (pending: number) => {
            if (epoch !== this.epoch || !layer.show) return;
            if (pending > 0) {
              if (settled) {
                settled = false;
                failures = 0;
                clearTimeout(deadline);
                deadline = setTimeout(() => {
                  if (!settled) fallback();
                }, 25000);
                this.changed({
                  mode,
                  state: "loading",
                  message: "Loading detail for this view…",
                });
              }
              return;
            }
            if (settled) return;
            if (failures) {
              fallback();
              return;
            }
            settled = true;
            clearTimeout(deadline);
            this.changed({
              mode,
              state: "ready",
              message:
                mode === "satellite"
                  ? "Satellite imagery · detail varies by location"
                  : "Street map · OpenStreetMap",
            });
          },
        );
      this.cleanup = () => {
        clearTimeout(retry);
        clearTimeout(deadline);
        removeError();
        removeProgress();
      };
      this.viewer.scene.requestRender();
    } catch {
      if (epoch === this.epoch)
        this.changed({
          mode,
          state: "fallback",
          message: "Map could not load. Reload Earth to retry.",
        });
    }
  }
  /** Called with true when the local reference package failed to load. */
  setReferenceFallback(enabled: boolean) {
    if (this.referenceFallback === enabled) return;
    this.referenceFallback = enabled;
    // Add or drop only the reference layer. Re-running set() would rebuild the
    // imagery layer and flash the globe.
    this.applyReference();
    if (!this.viewer.isDestroyed()) this.viewer.scene.requestRender();
  }
  private applyReference() {
    const wanted =
      this.referenceFallback && this.mode === "satellite" && !!this.overlay;
    if (!wanted) {
      this.removeReference();
      return;
    }
    if (this.reference || this.viewer.isDestroyed()) return;
    this.reference = this.viewer.imageryLayers.addImageryProvider(
      new UrlTemplateImageryProvider({
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        maximumLevel: 19,
        credit: new Credit(
          "Esri, Garmin, FAO, NOAA, USGS · boundaries and place names",
          true,
        ),
      }),
    );
    this.reference.show = this.overlay?.show ?? true;
  }
  private removeReference() {
    if (this.reference && !this.viewer.isDestroyed())
      this.viewer.imageryLayers.remove(this.reference, true);
    this.reference = undefined;
  }
  destroy() {
    ++this.epoch;
    this.cleanup();
  }
}
