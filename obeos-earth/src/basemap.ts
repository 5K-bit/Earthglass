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
      let retry: ReturnType<typeof setTimeout> | undefined;
      let failures = 0,
        settled = false;
      const fallback = () => {
        if (epoch !== this.epoch || this.viewer.isDestroyed()) return;
        settled = true;
        layer.show = false;
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
  destroy() {
    ++this.epoch;
    this.cleanup();
  }
}
