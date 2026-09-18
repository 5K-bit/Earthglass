import {
  Cartesian2,
  Cartesian3,
  Color,
  ConstantPositionProperty,
  ConstantProperty,
  CustomDataSource,
  EllipseGraphics,
  PolylineGraphics,
  Matrix4,
  PointGraphics,
  LabelGraphics,
} from "cesium";
import type { Viewer } from "cesium";
export type PrivatePosition = {
  device_id: string;
  latitude: number;
  longitude: number;
  altitude_m: number | null;
  accuracy_m: number | null;
  speed_mps: number | null;
  heading_deg: number | null;
  battery_percent?: number | null;
  recorded_at: string;
  received_at: string;
};
export type PrivateDevice = {
  device_id: string;
  label: string;
  status: string;
  age_seconds: number | null;
  tracking_enabled: boolean;
  position: PrivatePosition | null;
  retention_days: number;
  permissions: { history: boolean };
};
export class PresenceRenderer {
  private source = new CustomDataSource("private-presence");
  private following: string | null = null;
  private distance = 8000;
  private oldView: {
    destination: Cartesian3;
    orientation: { heading: number; pitch: number; roll: number };
  } | null = null;
  constructor(private viewer: Viewer) {
    void viewer.dataSources.add(this.source);
  }
  get visible() {
    return this.source.entities.values.length > 0;
  }
  update(devices: PrivateDevice[], accuracy: boolean) {
    if (!devices.some((d) => d.position)) {
      this.clear();
      return;
    }
    if (!this.oldView && devices.some((d) => d.position)) {
      const camera = this.viewer.camera;
      this.oldView = {
        destination: Cartesian3.clone(camera.positionWC),
        orientation: {
          heading: camera.heading,
          pitch: camera.pitch,
          roll: camera.roll,
        },
      };
    }
    const keep = new Set<string>();
    for (const device of devices) {
      const p = device.position;
      if (!p) continue;
      keep.add(device.device_id);
      const entity = this.source.entities.getOrCreateEntity(
        "private:" + device.device_id,
      );
      entity.position = new ConstantPositionProperty(
        Cartesian3.fromDegrees(
          p.longitude,
          p.latitude,
          Math.max(0, p.altitude_m ?? 0),
        ),
      );
      entity.point = new PointGraphics({
        pixelSize: 10,
        color: Color.fromCssColorString(
          device.status === "live" ? "#8bd8ae" : "#a9afb7",
        ),
        outlineColor: Color.BLACK,
        outlineWidth: 2,
      });
      entity.label = new LabelGraphics({
        text: device.label + " · " + device.status,
        font: "12px sans-serif",
        fillColor: Color.fromCssColorString("#d4eddf"),
        pixelOffset: new Cartesian2(12, -14),
      });
      entity.ellipse =
        accuracy && p.accuracy_m != null
          ? new EllipseGraphics({
              semiMajorAxis: Math.max(1, p.accuracy_m),
              semiMinorAxis: Math.max(1, p.accuracy_m),
              material: Color.fromCssColorString("#81dca8").withAlpha(0.13),
              outline: true,
              outlineColor: Color.fromCssColorString("#81dca8"),
            })
          : undefined;
      if (this.following === device.device_id)
        this.follow(device.device_id, this.distance);
    }
    for (const entity of this.source.entities.values.slice())
      if (entity.id.startsWith("private:") && !keep.has(entity.id.slice(8)))
        this.source.entities.remove(entity);
    if (this.following && !keep.has(this.following)) this.stopFollow();
    this.viewer.scene.requestRender();
  }
  trail(values: PrivatePosition[]) {
    this.source.entities.removeById("private-trail");
    const ordered = values
      .slice(-2000)
      .sort((a, b) => Date.parse(a.recorded_at) - Date.parse(b.recorded_at));
    if (ordered.length > 1)
      this.source.entities.add({
        id: "private-trail",
        polyline: new PolylineGraphics({
          positions: ordered.map((p) =>
            Cartesian3.fromDegrees(
              p.longitude,
              p.latitude,
              Math.max(2, p.altitude_m ?? 2),
            ),
          ),
          width: 2,
          material: Color.fromCssColorString("#81dca8").withAlpha(0.65),
        }),
      });
    this.viewer.scene.requestRender();
  }
  follow(id: string, distance: number) {
    const entity = this.source.entities.getById("private:" + id);
    if (!entity) return;
    if (!this.oldView) {
      const camera = this.viewer.camera;
      this.oldView = {
        destination: Cartesian3.clone(camera.positionWC),
        orientation: {
          heading: camera.heading,
          pitch: camera.pitch,
          roll: camera.roll,
        },
      };
    }
    this.following = id;
    this.distance = distance;
    entity.viewFrom = new ConstantProperty(
      new Cartesian3(-distance, 0, distance * 0.55),
    );
    this.viewer.trackedEntity = entity;
    this.viewer.scene.requestRender();
  }
  stopFollow() {
    if (!this.following && !this.oldView) return;
    if (this.following) this.viewer.trackedEntity = undefined;
    this.following = null;
    this.viewer.camera.lookAtTransform(Matrix4.IDENTITY);
    if (this.oldView) {
      this.viewer.camera.setView(this.oldView);
      this.oldView = null;
    }
  }
  clear() {
    this.stopFollow();
    this.source.entities.removeAll();
    this.viewer.scene.requestRender();
  }
  destroy() {
    this.stopFollow();
    this.viewer.dataSources.remove(this.source, true);
  }
}
