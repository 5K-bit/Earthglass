import {
  Cartesian2, Cartesian3, Color, CustomDataSource,
  LabelStyle, Math as CesiumMath, SceneTransforms,
  GeoJsonDataSource, PolylineDashMaterialProperty,
} from "cesium";
import type { Viewer } from "cesium";
import { request } from "./controlApi";

type Feature = {
  id: string;
  geometry: { coordinates: [number, number] };
  properties: { name: string; category: string; rank: number };
};

export class ReferenceLabels {
  private source = new CustomDataSource("reference-labels");
  private features: Feature[] = [];
  private abort = new AbortController();
  private disposed = false;
  private boundaries = new GeoJsonDataSource("reference-boundaries");
  private removeMove: () => void;

  constructor(
    private viewer: Viewer,
    private report: (message: string) => void,
  ) {
    void viewer.dataSources.add(this.source);
    this.removeMove = viewer.camera.moveEnd.addEventListener(() => this.render());
    void this.load();
    void this.loadBoundaries();
  }

  private async loadBoundaries() {
    try {
      const data = await request<object>("/api/maps/reference/boundaries", { signal: this.abort.signal });
      if (this.disposed) return;
      await this.boundaries.load(data, { stroke: Color.fromCssColorString("#e1d1a0").withAlpha(0.65), strokeWidth: 1.2, clampToGround: false });
      if (this.disposed) return;
      for (const entity of this.boundaries.entities.values) {
        if (entity.polyline && entity.properties?.disputed?.getValue()) {
          entity.polyline.material = new PolylineDashMaterialProperty({ color: Color.fromCssColorString("#e3b777"), dashLength: 12 });
        }
      }
      await this.viewer.dataSources.add(this.boundaries);
      if (this.disposed) {
        if (!this.viewer.isDestroyed()) this.viewer.dataSources.remove(this.boundaries, true);
        return;
      }
      this.viewer.scene.requestRender();
    } catch {
      if (!this.disposed) this.report("Offline reference boundaries unavailable; install the boundary package.");
    }
  }

  private async load() {
    try {
      const data = await request<{ features: Feature[] }>(
        "/api/maps/reference/labels", { signal: this.abort.signal },
      );
      if (this.disposed) return;
      this.features = data.features.sort((a, b) =>
        (a.properties.category === "cities" ? 1 : 0) -
        (b.properties.category === "cities" ? 1 : 0) ||
        a.properties.rank - b.properties.rank);
      this.render();
    } catch {
      if (this.disposed) return;
      this.report("Offline reference labels unavailable; install the global reference package.");
    }
  }

  private render() {
    if (this.disposed || this.viewer.isDestroyed()) return;
    const { scene, camera } = this.viewer;
    const bounds = camera.computeViewRectangle(scene.globe.ellipsoid);
    const altitude = camera.positionCartographic.height;
    const occupied: { x: number; y: number; width: number }[] = [];
    const retained = new Set<string>();
    this.source.entities.suspendEvents();
    try {
      for (const feature of this.features) {
        const p = feature.properties;
        if (p.category === "states" && (altitude > 5e6 || altitude < 5e4)) continue;
        if (p.category === "cities" && p.rank > (altitude > 5e6 ? 1 : altitude > 1e6 ? 4 : 10)) continue;
        const [lon, lat] = feature.geometry.coordinates;
        if (bounds) {
          const west = CesiumMath.toDegrees(bounds.west), east = CesiumMath.toDegrees(bounds.east);
          if (lat < CesiumMath.toDegrees(bounds.south) || lat > CesiumMath.toDegrees(bounds.north)) continue;
          if (west <= east ? lon < west || lon > east : lon < west && lon > east) continue;
        }
        const position = Cartesian3.fromDegrees(lon, lat);
        const normal = scene.globe.ellipsoid.geodeticSurfaceNormal(position);
        const towardCamera = Cartesian3.subtract(camera.positionWC, position, new Cartesian3());
        if (Cartesian3.dot(normal, towardCamera) <= 0) continue;
        const screen = SceneTransforms.worldToWindowCoordinates(scene, position);
        if (!screen || screen.x < 0 || screen.y < 0 || screen.x > scene.canvas.clientWidth || screen.y > scene.canvas.clientHeight) continue;
        const width = Math.min(300, p.name.length * 8 + 20);
        if (occupied.some(box => Math.abs(box.x - screen.x) < (box.width + width) / 2 && Math.abs(box.y - screen.y) < 24)) continue;
        occupied.push({ x: screen.x, y: screen.y, width });
        const id = `reference:${feature.id}`;
        retained.add(id);
        if (!this.source.entities.getById(id)) this.source.entities.add({
          id, position,
          label: { text: p.name, font: p.category === "cities" ? "bold 13px sans-serif" : "bold 15px sans-serif",
            fillColor: p.category === "oceans" ? Color.LIGHTBLUE : Color.WHITE,
            style: LabelStyle.FILL_AND_OUTLINE, outlineColor: Color.BLACK.withAlpha(0.85),
            outlineWidth: 4, pixelOffset: new Cartesian2(0, -8) },
        });
        if (occupied.length >= 250) break;
      }
      for (const entity of [...this.source.entities.values]) {
        if (!retained.has(entity.id)) this.source.entities.remove(entity);
      }
    } finally { this.source.entities.resumeEvents(); }
    scene.requestRender();
  }

  /** Off while the tiled reference overlays carry the labels, so the two label
   *  sets never draw together. Data sources stay loaded, so it is reversible. */
  setEnabled(enabled: boolean) {
    if (this.disposed || this.viewer.isDestroyed()) return;
    if (this.source.show === enabled) return;
    this.source.show = enabled;
    this.boundaries.show = enabled;
    this.viewer.scene.requestRender();
  }
  destroy() {
    this.disposed = true;
    this.abort.abort();
    this.removeMove();
    this.viewer.dataSources.remove(this.source, true);
    this.viewer.dataSources.remove(this.boundaries, true);
  }
}
