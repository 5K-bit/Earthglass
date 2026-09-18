import { UrlTemplateImageryProvider, Credit } from "cesium";
import type { Viewer, ImageryLayer } from "cesium";
import { request } from "./controlApi";
export type ImageryProduct = {
  id: string;
  label: string;
  available: boolean;
  maximum_level: number;
  default_time: string;
  attribution: string;
  provider: string;
};
export class ImageryController {
  private layers = new Map<
    string,
    { layer: ImageryLayer; key: string; cleanup: () => void }
  >();
  private revision = 0;
  private desired = "";
  private destroyed = false;
  constructor(
    private viewer: Viewer,
    private report: (message: string) => void,
  ) {}
  apply(
    products: ImageryProduct[],
    enabled: { product: string; opacity: number }[],
    at: string | null,
  ) {
    const key = JSON.stringify([products, enabled, at]);
    if (key === this.desired) return;
    this.desired = key;
    const revision = ++this.revision;
    const wanted = new Set(enabled.slice(0, 2).map((p) => p.product));
    for (const [id, old] of this.layers)
      if (!wanted.has(id)) {
        old.cleanup();
        this.viewer.imageryLayers.remove(old.layer, true);
        this.layers.delete(id);
      }
    for (const choice of enabled.slice(0, 2)) {
      const product = products.find(
        (p) => p.id === choice.product && p.available,
      );
      if (!product) continue;
      void request<{ time: string }>(
        "/api/v2/imagery/frame/" +
          encodeURIComponent(product.id) +
          (at ? "?at=" + encodeURIComponent(at) : ""),
      )
        .then((frame) => {
          if (this.destroyed || revision !== this.revision) return;
          const instant = frame.time,
            key = product.id + "/" + instant,
            old = this.layers.get(product.id);
          if (old?.key === key) {
            old.layer.alpha = choice.opacity;
            this.viewer.scene.requestRender();
            return;
          }
          if (old) {
            old.cleanup();
            this.viewer.imageryLayers.remove(old.layer, true);
            this.layers.delete(product.id);
          }
          const provider = new UrlTemplateImageryProvider({
            url:
              "/api/v2/imagery/tiles/" +
              encodeURIComponent(product.id) +
              "/" +
              encodeURIComponent(instant) +
              "/{z}/{x}/{y}",
            maximumLevel: product.maximum_level,
            credit: new Credit(product.attribution + " · " + instant, true),
          });
          const layer = this.viewer.imageryLayers.addImageryProvider(provider);
          layer.alpha = choice.opacity;
          const cleanup = provider.errorEvent.addEventListener(() =>
            this.report(
              product.label +
                ": some tiles unavailable for " +
                instant +
                "; base imagery remains visible",
            ),
          );
          this.layers.set(product.id, { layer, key, cleanup });
          this.viewer.scene.requestRender();
        })
        .catch(() => {
          if (this.destroyed || revision !== this.revision) return;
          const old = this.layers.get(product.id);
          if (old) {
            old.cleanup();
            this.viewer.imageryLayers.remove(old.layer, true);
            this.layers.delete(product.id);
          }
          this.report(product.label + ": no frame is available at this time");
          this.viewer.scene.requestRender();
        });
    }
    this.viewer.scene.requestRender();
  }
  destroy() {
    this.destroyed = true;
    ++this.revision;
    for (const v of this.layers.values()) v.cleanup();
    this.layers.clear();
  }
}
