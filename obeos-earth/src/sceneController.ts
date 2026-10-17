import {
  Viewer,
  SingleTileImageryProvider,
  Rectangle,
  ImageryLayer,
  Cartesian2,
  Cartesian3,
  Color,
  CustomDataSource,
  ConstantPositionProperty,
  SampledPositionProperty,
  ExtrapolationType,
  ConstantProperty,
  CallbackProperty,
  CallbackPositionProperty,
  NearFarScalar,
  DistanceDisplayCondition,
  LabelStyle,
  Math as CesiumMath,
  Entity,
  HeadingPitchRange,
  Matrix4,
  EllipsoidTerrainProvider,
  ScreenSpaceEventType,
  ScreenSpaceEventHandler,
  JulianDate,
  PolylineGraphics,
  ColorMaterialProperty,
  PolygonHierarchy,
  PolygonGraphics,
  EllipseGraphics,
  ModelGraphics,
  Transforms,
  HeadingPitchRoll,
} from "cesium";
import type { Observation, Viewport } from "./contracts";
import type { SceneState, Annotation } from "./controlApi";
import { isNewer } from "./controlApi";
import { reconcile } from "./contactIndex";
import { RenderGovernor } from "./renderGovernor";
import { needsLocalReferenceLabels } from "./mapChoice";

const colors: Record<string, string> = {
  aircraft: "#7ee0ea",
  military: "#dfb46b",
  vessels: "#6aaafa",
  satellites: "#b49cff",
  earthquakes: "#efa778",
  fires: "#ff6767",
  weather: "#88cce5",
  temperature: "#edb277",
  infrastructure: "#c3cad2",
  launches: "#b79aed",
  bikeshare: "#83d4a0",
  traffic: "#ecc679",
  cctv: "#d0dbe6",
  weather_alerts: "#ed9674",
  natural_events: "#edbb7a",
  wind: "#85cdd2",
  clouds: "#b2c5d1",
  pressure: "#b09bda",
  precipitation: "#66b6e0",
  traffic_speeds: "#e9c86f",
  traffic_incidents: "#ea916e",
  transit_vehicles: "#7ecdb0",
  transit_routes: "#76b4ad",
  transit_stops: "#abcbc5",
  perception: "#d58fe9",
};
import { label } from "./observationLabel";
import { canInterpolateTransit } from "./transitMotion";
import { viewportSignature } from "./viewportChange";
import { CameraMotion } from "./cameraMotion";
import { inViewport, selectVisibleDetail } from "./visibleDetail";
import {
  observationIsStale,
  observationVisibleAt,
} from "./observationFreshness";
import { BasemapController } from "./basemap";
import { ReferenceLabels } from "./referenceLabels";
import { ImageryController, type ImageryProduct } from "./imageryController";
import type { Basemap, MapStatus } from "./mapChoice";
import {
  PresenceRenderer,
  type PrivateDevice,
  type PrivatePosition,
} from "./presenceRenderer";
export class SceneController {
  readonly viewer: Viewer;
  readonly governor: RenderGovernor;
  readonly observations = new Map<string, Observation>();
  private cameraMotion = new CameraMotion();
  private source = new CustomDataSource("observations");
  private annotations = new CustomDataSource("annotations");
  private polygons = new CustomDataSource("area-polygons");
  private polygonChildren = new Map<string, string[]>();
  private polygonParents = new Map<string, string>();
  private trailSource = new CustomDataSource("selected-trail");
  private trails = new Map<string, Cartesian3[]>();
  private transitMotion = new Map<
    string,
    { from: Cartesian3; to: Cartesian3; started: number }
  >();
  private renderKeys = new Map<string, string>();
  private selected: string | null = null;
  private pendingCamera: SceneState | null = null;
  private sceneInitialized = false;
  private replayAt: string | null = null;
  private enabled = new Set<string>();
  private removeTick: () => void;
  private cameraMode = "";
  private cameraEntity: string | null = null;
  private distance = 5000;
  private destroyed = false;
  private basemap: BasemapController;
  private referenceLabels: ReferenceLabels;
  private imagery?: ImageryController;
  private presence?: PresenceRenderer;
  private privateSelection?: (id: string) => void;
  onPrivateSelection(select?: (id: string) => void) {
    this.privateSelection = select;
  }
  setPrivatePresence(devices: PrivateDevice[], accuracy: boolean) {
    this.presence ??= new PresenceRenderer(this.viewer);
    this.presence.update(devices, accuracy);
  }
  setPrivateTrail(values: PrivatePosition[]) {
    this.presence?.trail(values);
  }
  followPrivate(id: string, distance: number) {
    this.presence?.follow(id, distance);
  }
  stopPrivateFollow() {
    this.presence?.stopFollow();
  }
  clearPrivatePresence() {
    this.presence?.clear();
  }
  setImagery(products: ImageryProduct[], state: SceneState) {
    this.imagery ??= new ImageryController(this.viewer, this.onError);
    this.imagery.apply(products, state.imagery ?? [], state.timeline.at);
  }
  private reportedViewport = "";
  private timer: ReturnType<typeof setInterval>;
  private handler: ScreenSpaceEventHandler;
  constructor(
    container: HTMLElement,
    private onSelect: (id: string) => void,
    private onViewport: (
      viewport: Viewport,
      camera: { latitude: number; longitude: number; altitude_m: number },
    ) => void,
    private onError: (message: string) => void,
    onMapStatus: (status: MapStatus) => void,
  ) {
    this.viewer = new Viewer(container, {
      animation: false,
      timeline: false,
      baseLayerPicker: false,
      baseLayer: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: true,
      shouldAnimate: false,
      requestRenderMode: true,
      terrainProvider: new EllipsoidTerrainProvider(),
      contextOptions: { webgl: { preserveDrawingBuffer: true, alpha: false } },
    });
    this.viewer.scene.globe.baseColor = Color.fromCssColorString("#1b3546");
    this.viewer.scene.backgroundColor = Color.fromCssColorString("#080d14");
    this.viewer.scene.globe.maximumScreenSpaceError = 4;
    this.viewer.scene.fog.enabled = false;
    this.viewer.scene.globe.enableLighting = true;
    if (this.viewer.scene.skyAtmosphere) this.viewer.scene.skyAtmosphere.show = true;
    this.viewer.scene.postProcessStages.fxaa.enabled = true;
    this.source.clustering.enabled = true;
    this.source.clustering.pixelRange = 35;
    this.source.clustering.minimumClusterSize = 4;
    this.source.clustering.clusterEvent.addEventListener(
      (entities, cluster) => {
        cluster.billboard.show = false;
        cluster.point.show = true;
        cluster.point.pixelSize = 10;
        cluster.point.color = Color.fromCssColorString("#27434f");
        cluster.point.outlineColor = Color.fromCssColorString("#7ee0ea");
        cluster.point.outlineWidth = 1;
        cluster.label.show = true;
        cluster.label.text = entities.length.toLocaleString();
        cluster.label.font = "11px sans-serif";
        cluster.label.fillColor = Color.fromCssColorString("#b8d7df");
        cluster.label.outlineColor = Color.fromCssColorString("#15202b");
        cluster.label.outlineWidth = 2;
        cluster.label.pixelOffset = new Cartesian2(12, -6);
      },
    );
    void this.viewer.dataSources.add(this.source);
    void this.viewer.dataSources.add(this.annotations);
    void this.viewer.dataSources.add(this.polygons);
    void this.viewer.dataSources.add(this.trailSource);
    this.governor = new RenderGovernor(this.viewer);
    this.governor.onBudgetChange = () => this.renderContacts();
    this.viewer.camera.setView({
      destination: Cartesian3.fromDegrees(-35, 28, 16000000),
    });
    this.handler = new ScreenSpaceEventHandler(this.viewer.canvas);
    this.handler.setInputAction((event: { position: Cartesian2 }) => {
      const picked = this.viewer.scene.pick(event.position);
      if (picked?.id instanceof Entity) {
        if (picked.id.id.startsWith("private:")) {
          this.privateSelection?.(picked.id.id.slice(8));
          return;
        }
        const id = this.polygonParents.get(picked.id.id) ?? picked.id.id;
        if (this.observations.has(id)) this.onSelect(id);
      }
    }, ScreenSpaceEventType.LEFT_CLICK);
    this.viewer.camera.moveEnd.addEventListener(() => {
      if (this.reportViewport()) this.renderContacts();
    });
    this.viewer.scene.renderError.addEventListener(() =>
      this.onError("The renderer stopped. Reload Earth to recover your scene."),
    );
    this.removeTick = this.viewer.scene.preRender.addEventListener(() => {
      const camera = this.viewer.camera;
      const position = camera.positionWC, direction = camera.directionWC;
      this.governor.hold("camera", this.cameraMotion.sample(
        [position.x, position.y, position.z],
        [direction.x, direction.y, direction.z],
        camera.positionCartographic.height,
        performance.now(),
      ));
      for (const [id, motion] of this.transitMotion) {
        if (this.replayAt || performance.now() - motion.started >= 2000) {
          const entity = this.source.entities.getById(id);
          if (entity) entity.position = new ConstantPositionProperty(motion.to);
          this.transitMotion.delete(id);
        }
      }
      this.governor.hold("transit-motion", this.transitMotion.size > 0);
      if (
        this.cameraMode === "orbit" &&
        this.cameraEntity &&
        !this.presence?.visible
      ) {
        const entity = this.source.entities.getById(this.cameraEntity);
        const position = entity?.position?.getValue(JulianDate.now());
        if (position)
          this.viewer.camera.lookAt(
            position,
            new HeadingPitchRange(
              performance.now() / 18000,
              -0.55,
              this.distance,
            ),
          );
      }
    });
    this.timer = setInterval(() => {
      if (!document.hidden) {
        this.renderContacts();
        if (this.cameraMode === "follow" || this.cameraMode === "orbit")
          this.reportViewport();
      }
    }, 5000);
    // Online basemaps carry tiled cartography with a per-zoom label hierarchy.
    // The bundled Natural Earth labels are the offline floor, so they draw only
      // in offline mode or after tile failure, without duplicating online labels.
    this.basemap = new BasemapController(this.viewer, (status) => {
      this.referenceLabels?.setEnabled(needsLocalReferenceLabels(status));
      onMapStatus(status);
    });
    this.referenceLabels = new ReferenceLabels(this.viewer, onError);
  }
  private position(o: Observation) {
    // Depth is never rendered as aviation altitude. Unknown altitude stays a surface glyph.
    return Cartesian3.fromDegrees(
      o.position.longitude,
      o.position.latitude,
      Math.max(0, o.position.altitude_m ?? 0),
    );
  }
  upsert(values: Observation[], replace = false, preserveSelection = false) {
    const protectedIds = [this.selected, this.cameraEntity].filter(
      (id): id is string => Boolean(id),
    );
    if (!this.replayAt)
      for (const next of values) {
        const previous = this.observations.get(next.entity_id);
        if (!canInterpolateTransit(previous, next)) continue;
        const entity = this.source.entities.getById(next.entity_id);
        const from = entity?.position?.getValue(JulianDate.now());
        const to = this.position(next);
        if (from && Cartesian3.distance(from, to) < 10000)
          this.transitMotion.set(next.entity_id, {
            from: Cartesian3.clone(from),
            to,
            started: performance.now(),
          });
      }
    const changes = reconcile(
      this.observations,
      values,
      replace,
      preserveSelection || !replace ? protectedIds : [],
    );
    for (const id of changes.removed) {
      this.transitMotion.delete(id);
      this.trails.delete(id);
      this.renderKeys.delete(id);
      this.source.entities.removeById(id);
    }
    for (const value of changes.updated) {
      const trail = this.trails.get(value.entity_id) ?? [];
      trail.push(this.position(value));
      this.trails.set(value.entity_id, trail.slice(-90));
    }
    this.renderContacts();
    if (
      this.pendingCamera?.camera.entity_id &&
      this.source.entities.getById(this.pendingCamera.camera.entity_id)
    ) {
      const pending = this.pendingCamera;
      this.pendingCamera = null;
      this.cameraModeKey = "";
      this.apply(pending);
    }
  }
  remove(id: string) {
    this.observations.delete(id);
    this.transitMotion.delete(id);
    this.trails.delete(id);
    this.source.entities.removeById(id);
    this.governor.request();
  }
  setLayers(layers: string[]) {
    if (
      layers.length === this.enabled.size &&
      layers.every((layer) => this.enabled.has(layer))
    )
      return;
    this.enabled = new Set(layers);
    this.renderContacts();
  }
  select(id: string | null) {
    this.selected = id;
    this.renderContacts();
    this.viewer.selectedEntity = id
      ? this.source.entities.getById(id)
      : undefined;
  }
  setTrails(id: string, values: Observation[]) {
    this.renderKeys.delete(id);
    this.trails.set(
      id,
      values
        .map((o) => this.position(o))
        .reverse()
        .slice(-200),
    );
    this.renderContacts();
  }
  private renderContacts() {
    if (this.destroyed) return;
    const start = performance.now();
    const camera = this.viewer.camera.positionWC;
    const unique = new Map<string, Observation>();
    const rectangle = this.viewer.camera.computeViewRectangle();
    const view = rectangle
      ? {
          west: CesiumMath.toDegrees(rectangle.west),
          east: CesiumMath.toDegrees(rectangle.east),
          south: CesiumMath.toDegrees(rectangle.south),
          north: CesiumMath.toDegrees(rectangle.north),
        }
      : null;
    for (const o of this.observations.values()) {
      if (o.entity_id !== this.selected && view && !inViewport(o, view))
        continue;
      if (!this.enabled.has(o.layer) && o.entity_id !== this.selected) continue;
      if (
        !observationVisibleAt(
          o,
          this.replayAt ? Date.parse(this.replayAt) : Date.now(),
        )
      )
        continue;
      if (
        o.layer === "transit_vehicles" &&
        this.viewer.camera.positionCartographic.height > 1500000
      )
        continue;
      const key = String(o.properties?.canonical_entity_id ?? o.entity_id),
        old = unique.get(key);
      if (
        !old ||
        o.entity_id === this.selected ||
        (old.entity_id !== this.selected && isNewer(o, old))
      )
        unique.set(key, o);
    }
    const distances = new Map(
      [...unique.values()].map((o) => [
        o.entity_id,
        Cartesian3.distanceSquared(camera, this.position(o)),
      ]),
    );
    const visible = [...unique.values()];
    visible.sort((a, b) =>
      a.entity_id === this.selected
        ? -1
        : b.entity_id === this.selected
          ? 1
          : distances.get(a.entity_id)! - distances.get(b.entity_id)!,
    );
    const limited = selectVisibleDetail(
      visible,
      this.governor.detailBudget,
      this.selected,
    );
    const moving =
      !this.replayAt &&
      limited.some((o) => o.layer === "satellites" && !observationIsStale(o));
    this.viewer.clock.shouldAnimate = moving;
    this.governor.hold("satellite-motion", moving);
    if (this.replayAt) this.transitMotion.clear();
    this.governor.hold("transit-motion", this.transitMotion.size > 0);
    this.governor.hold(
      "selected-earthquake",
      limited.some(
        (o) => o.entity_id === this.selected && o.layer === "earthquakes",
      ),
    );
    const keep = new Set(limited.map((o) => o.entity_id));
    for (const [parent, children] of this.polygonChildren)
      if (!keep.has(parent)) {
        for (const child of children) {
          this.polygons.entities.removeById(child);
          this.polygonParents.delete(child);
        }
        this.polygonChildren.delete(parent);
      }
    this.source.entities.suspendEvents();
    for (const entity of this.source.entities.values.slice())
      if (!keep.has(entity.id)) {
        this.source.entities.remove(entity);
        this.renderKeys.delete(entity.id);
      }
    limited.forEach((o, index) => {
      let entity = this.source.entities.getById(o.entity_id);
      const congestionColors: Record<string, string> = {
        free_flow: "#7cd7a3",
        slow: "#e7c36b",
        stopped: "#ea7b6a",
      };
      const color = Color.fromCssColorString(
        (o.layer === "traffic_speeds"
          ? congestionColors[String(o.properties?.congestion)]
          : undefined) ??
          colors[o.layer] ??
          "#bfc8d4",
      );
      const selected = o.entity_id === this.selected;
      const stale = observationIsStale(o);
      const version = JSON.stringify([
        o,
        selected,
        index < 18,
        index < 12,
        index < 300,
        index < 150,
        stale,
      ]);
      if (entity && this.renderKeys.get(o.entity_id) === version) return;
      this.renderKeys.set(o.entity_id, version);
      if (!entity)
        entity = this.source.entities.add({
          id: o.entity_id,
          position: this.position(o),
          point: {
            pixelSize: 6,
            color,
            outlineColor: Color.fromCssColorString("#15202b"),
            outlineWidth: 1,
            scaleByDistance: new NearFarScalar(1000, 1.6, 2e7, 0.65),
          },
          label: {
            text: label(o),
            font: "500 14px sans-serif",
            fillColor: Color.fromCssColorString("#eff7fa"),
            style: LabelStyle.FILL_AND_OUTLINE,
            outlineColor: Color.fromCssColorString("#142029"),
            outlineWidth: 1,
            showBackground: true,
            backgroundColor: Color.fromCssColorString("#142029").withAlpha(0.8),
            backgroundPadding: new Cartesian2(5, 3),
            pixelOffset: new Cartesian2(10, -12),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 800000),
            show: false,
          },
        });
      entity.position = new ConstantPositionProperty(this.position(o));
      const transition = this.transitMotion.get(o.entity_id);
      if (transition && !this.replayAt)
        entity.position = new CallbackPositionProperty(
          (_time, result) =>
            Cartesian3.lerp(
              transition.from,
              transition.to,
              Math.min(
                1,
                Math.max(0, (performance.now() - transition.started) / 2000),
              ),
              result ?? new Cartesian3(),
            ),
          false,
        );
      const samples = o.properties?.prediction_samples as
        | {
            time: string;
            latitude: number;
            longitude: number;
            altitude_m: number;
          }[]
        | undefined;
      if (o.layer === "satellites" && samples?.length && !this.replayAt) {
        const sampled = new SampledPositionProperty();
        for (const sample of samples)
          sampled.addSample(
            JulianDate.fromIso8601(sample.time),
            Cartesian3.fromDegrees(
              sample.longitude,
              sample.latitude,
              sample.altitude_m,
            ),
          );
        sampled.forwardExtrapolationType = ExtrapolationType.HOLD;
        sampled.forwardExtrapolationDuration = 0;
        entity.position = sampled;
      }
      if (entity.point) {
        entity.point.pixelSize = new ConstantProperty(
          selected ? 11 : o.layer === "earthquakes" ? 7 : 5,
        );
        entity.point.color = new ConstantProperty(
          color.withAlpha(stale ? 0.5 : 1),
        );
      }
      if (entity.label) {
        entity.label.text = new ConstantProperty(label(o));
        entity.label.show = new ConstantProperty(selected || index < 18);
      }
      if (o.layer === "earthquakes" && entity.point) {
        const magnitude =
          typeof o.properties?.magnitude === "number"
            ? o.properties.magnitude
            : 0;
        const size = 5 + Math.max(0, magnitude) * 1.2;
        entity.point.pixelSize = selected
          ? new CallbackProperty(
              () => size + 2 + Math.sin(Date.now() / 350) * 1.5,
              false,
            )
          : new ConstantProperty(size);
      }
      for (const child of this.polygonChildren.get(o.entity_id) ?? []) {
        this.polygons.entities.removeById(child);
        this.polygonParents.delete(child);
      }
      this.polygonChildren.delete(o.entity_id);
      entity.ellipse = undefined;
      entity.polygon = undefined;
      entity.polyline = undefined;
      if (
        [
          "weather",
          "temperature",
          "wind",
          "precipitation",
          "pressure",
          "clouds",
        ].includes(o.layer)
      ) {
        const temp =
          typeof o.properties?.temperature_c === "number"
            ? o.properties.temperature_c
            : NaN;
        const tint = Number.isFinite(temp)
          ? Color.fromHsl(
              Math.max(0, Math.min(0.65, (40 - temp) / 70)),
              0.6,
              0.55,
              0.22,
            )
          : color.withAlpha(0.12);
        entity.ellipse = new EllipseGraphics({
          semiMajorAxis: Number(o.properties?.display_radius_m ?? 5000),
          semiMinorAxis: Number(o.properties?.display_radius_m ?? 5000),
          material: tint,
        });
        if (entity.label) {
          entity.label.text = new ConstantProperty(weatherLabel(o));
          entity.label.show = new ConstantProperty(index < 18 || selected);
        }
      }
      const geometry = o.properties?.geometry as
        { type?: string; coordinates?: number[][] } | undefined;
      if (
        geometry?.type === "LineString" &&
        geometry.coordinates &&
        index < 300
      ) {
        entity.polyline = new PolylineGraphics({
          positions: geometry.coordinates.map((p) =>
            Cartesian3.fromDegrees(p[0], p[1], 2),
          ),
          width: 2,
          material: color.withAlpha(0.65),
        });
      }
      if (
        (geometry?.type === "Polygon" || geometry?.type === "MultiPolygon") &&
        index < 150
      ) {
        const raw = geometry.coordinates as unknown as
          number[][][] | number[][][][];
        const polygons = (
          geometry.type === "Polygon" ? [raw] : raw
        ) as number[][][][];
        const children: string[] = [];
        const ring = (points: number[][]) =>
          new PolygonHierarchy(
            points.map((p) => Cartesian3.fromDegrees(p[0], p[1])),
          );
        for (const [part, rings] of polygons.slice(0, 8).entries()) {
          if (!rings?.[0] || rings[0].length < 4) continue;
          const graphic = new PolygonGraphics({
            hierarchy: new PolygonHierarchy(
              ring(rings[0]).positions,
              rings.slice(1).map(ring),
            ),
            material: color.withAlpha(0.16),
            outline: true,
            outlineColor: color.withAlpha(0.8),
            height: 0,
          });
          if (part === 0) entity.polygon = graphic;
          else {
            const id = "area:" + o.entity_id + ":" + part;
            this.polygons.entities.getOrCreateEntity(id).polygon = graphic;
            this.polygonParents.set(id, o.entity_id);
            children.push(id);
          }
        }
        this.polygonChildren.set(o.entity_id, children);
      }
      const modelName =
        o.layer === "aircraft" || o.layer === "military"
          ? "aircraft"
          : o.layer === "vessels"
            ? "vessel"
            : o.layer === "satellites"
              ? "satellite"
              : null;
      if (modelName && (selected || index < 12)) {
        entity.model = new ModelGraphics({
          uri: "/models/" + modelName + ".gltf",
          minimumPixelSize: selected ? 45 : 25,
          maximumScale: 100,
          distanceDisplayCondition: new DistanceDisplayCondition(
            0,
            selected ? 2000000 : 100000,
          ),
        });
        entity.orientation = new ConstantProperty(
          Transforms.headingPitchRollQuaternion(
            this.position(o),
            new HeadingPitchRoll(
              CesiumMath.toRadians(o.motion?.heading_deg ?? 0),
              0,
              0,
            ),
          ),
        );
      } else entity.model = undefined;
    });
    this.source.entities.resumeEvents();
    // Keep trails separate: Cesium centers selection/tracking on an entity's complete bounding sphere.
    // Including a long trail moves that center away from the aircraft.
    const trail = this.selected ? this.trails.get(this.selected) : undefined;
    if (trail && trail.length > 1) {
      const trailEntity =
        this.trailSource.entities.getOrCreateEntity("selected-trail");
      trailEntity.polyline = new PolylineGraphics({
        positions: trail,
        width: 2,
        material: Color.fromCssColorString("#7ee0ea").withAlpha(0.65),
      });
    } else this.trailSource.entities.removeAll();
    this.viewer.selectedEntity = this.selected
      ? this.source.entities.getById(this.selected)
      : undefined;
    if (
      this.cameraMode === "follow" &&
      this.cameraEntity &&
      !this.presence?.visible
    )
      this.viewer.trackedEntity = this.source.entities.getById(
        this.cameraEntity,
      );
    window.earthMetrics = {
      ...window.earthMetrics,
      knownTracks: this.observations.size,
      renderedTracks: limited.length,
      updateMs: performance.now() - start,
    };
    this.governor.request();
  }
  apply(state: SceneState) {
    if (this.replayAt !== state.timeline.at) {
      this.replayAt = state.timeline.at;
      this.renderKeys.clear();
      this.viewer.clock.currentTime = state.timeline.at
        ? JulianDate.fromIso8601(state.timeline.at)
        : JulianDate.now();
      this.renderContacts();
    }
    const initial = !this.sceneInitialized;
    this.sceneInitialized = true;
    if (initial && state.view) {
      this.viewer.camera.setView({
        destination: Cartesian3.fromDegrees(
          state.view.longitude,
          state.view.latitude,
          state.view.altitude_m,
        ),
      });
      this.reportViewport();
    }
    this.select(state.selected_entity_id);
    const camera = state.camera;
    const key = JSON.stringify([camera, state.camera_revision ?? 0]);
    if (key !== this.cameraModeKey) {
      this.cameraModeKey = key;
      this.pendingCamera = null;
      this.cameraMode = camera.mode;
      this.cameraEntity = camera.entity_id ?? null;
      this.distance = camera.distance_m ?? 5000;
      this.viewer.trackedEntity = undefined;
      this.viewer.camera.lookAtTransform(Matrix4.IDENTITY);
      const cameraReady = Boolean(camera.entity_id && this.source.entities.getById(camera.entity_id));
      this.governor.hold("orbit", camera.mode === "orbit" && cameraReady);
      this.governor.hold("tracking", camera.mode === "follow" && cameraReady);
      if (
        (!initial || !state.view) &&
        (camera.mode === "goto" || camera.mode === "reset")
      )
        this.viewer.camera.flyTo({
          destination: Cartesian3.fromDegrees(
            camera.longitude ?? -35,
            camera.latitude ?? 28,
            camera.altitude_m ?? 16000000,
          ),
          duration: 1.1,
        });
      if (camera.entity_id) {
        const entity = this.source.entities.getById(camera.entity_id);
        this.pendingCamera = entity ? null : state;
        if (camera.mode === "follow" && entity) {
          entity.viewFrom = new ConstantProperty(
            new Cartesian3(-this.distance, 0, this.distance * 0.45),
          );
          this.viewer.trackedEntity = entity;
        }
        if (camera.mode === "overhead" && entity?.position) {
          const position = entity.position.getValue(JulianDate.now());
          if (position) {
            this.viewer.camera.lookAt(
              position,
              new HeadingPitchRange(0, -Math.PI / 2, this.distance),
            );
            this.viewer.camera.lookAtTransform(Matrix4.IDENTITY);
          }
        }
      }
    }
    this.applyAnnotations(state.annotations);
  }
  private cameraModeKey = "";
  private annotationKey = "";
  private applyAnnotations(values: Annotation[]) {
    const key = JSON.stringify(values);
    if (key === this.annotationKey) return;
    this.annotationKey = key;
    this.annotations.entities.removeAll();
    for (const a of values) {
      const color = Color.fromCssColorString(
        a.color === "gold"
          ? "#dfb46b"
          : a.color === "cyan"
            ? "#7ee0ea"
            : a.color === "red"
              ? "#ff6767"
              : "#ffffff",
      );
      const positions = a.coordinates.map((p) =>
        Cartesian3.fromDegrees(p[0], p[1], 5),
      );
      this.annotations.entities.add({
        id: "annotation:" + a.annotation_id,
        position: positions[0],
        label: {
          text: a.label,
          font: "13px sans-serif",
          fillColor: color,
          pixelOffset: new Cartesian2(12, -14),
        },
        point: a.geometry === "point" ? { pixelSize: 9, color } : undefined,
        polyline:
          a.geometry === "line"
            ? new PolylineGraphics({ positions, width: 3, material: color })
            : undefined,
        polygon:
          a.geometry === "polygon"
            ? new PolygonGraphics({
                hierarchy: new PolygonHierarchy(positions),
                material: new ColorMaterialProperty(color.withAlpha(0.2)),
                outline: true,
                outlineColor: color,
              })
            : undefined,
      });
    }
    this.governor.request();
  }
  setMap(mode: Exclude<Basemap, "auto">) {
    return this.basemap.set(mode);
  }
  mode(flat: boolean) {
    if (flat) this.viewer.scene.morphTo2D(0.8);
    else this.viewer.scene.morphTo3D(0.8);
    this.governor.request();
  }
  cinematic(enabled: boolean) {
    this.viewer.scene.globe.enableLighting = enabled;
    this.governor.request();
  }
  private weatherLayers = new Map<boolean, ImageryLayer>();
  private weatherEpoch = new Map<boolean, number>();
  async rasterWeather(layer: { metadata?: { cycle: string; assets: { image: string } } } | null, cloud: boolean) {
    const epoch = (this.weatherEpoch.get(cloud) ?? 0) + 1;
    this.weatherEpoch.set(cloud, epoch);
    const previous = this.weatherLayers.get(cloud);
    if (!layer?.metadata) {
      if (previous) this.viewer.imageryLayers.remove(previous, true);
      this.weatherLayers.delete(cloud);
      this.governor.request();
      return;
    }
    const url = layer.metadata.assets.image;
    if (!/^\/weather\/gfs\/latest\/[A-Za-z0-9_]+\.png$/.test(url)) throw new Error("Invalid weather asset path");
    const provider = await SingleTileImageryProvider.fromUrl(`${url}?cycle=${encodeURIComponent(layer.metadata.cycle)}`, {
      rectangle: Rectangle.fromDegrees(-180, -90, 180, 90),
      credit: `NOAA GFS model analysis · ${layer.metadata.cycle}`,
    });
    if (this.viewer.isDestroyed() || this.weatherEpoch.get(cloud) !== epoch) return;
    if (previous) this.viewer.imageryLayers.remove(previous, true);
    const imagery = this.viewer.imageryLayers.addImageryProvider(provider);
    imagery.alpha = cloud ? 0.55 : 0.65;
    this.weatherLayers.set(cloud, imagery);
    this.governor.request();
  }
  reportViewport() {
    if (this.presence?.visible) return; // Private device views must not be persisted or sent to public providers.
    const rectangle = this.viewer.camera.computeViewRectangle();
    if (!rectangle) return;
    const viewport = {
      west: CesiumMath.toDegrees(rectangle.west),
      south: CesiumMath.toDegrees(rectangle.south),
      east: CesiumMath.toDegrees(rectangle.east),
      north: CesiumMath.toDegrees(rectangle.north),
    };
    const camera = {
      latitude: CesiumMath.toDegrees(
        this.viewer.camera.positionCartographic.latitude,
      ),
      longitude: CesiumMath.toDegrees(
        this.viewer.camera.positionCartographic.longitude,
      ),
      altitude_m: Math.max(100, this.viewer.camera.positionCartographic.height),
    };
    const key = viewportSignature(viewport, camera);
    if (key === this.reportedViewport) return;
    this.reportedViewport = key;
    this.onViewport(viewport, camera);
    return true;
  }
  async capture(): Promise<string> {
    if (this.presence?.visible)
      throw new Error(
        "Hide private Presence before saving a public Earth scene.",
      );
    this.governor.request();
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        remove();
        reject(
          new Error("Snapshot timed out. Bring Earth into view and retry."),
        );
      }, 5000);
      const remove = this.viewer.scene.postRender.addEventListener(() => {
        clearTimeout(timeout);
        remove();
        resolve();
      });
    });
    const source = this.viewer.canvas;
    const attributions = [
      ...new Set(
        [...this.observations.values()]
          .filter((o) => this.enabled.has(o.layer))
          .map((o) => o.provenance.attribution),
      ),
    ];
    const basemap =
      this.viewer.container.querySelector(".cesium-widget-credits")
        ?.textContent ?? "Cesium / Natural Earth";
    const caption =
      "OBEOS Earth · " +
      new Date().toISOString() +
      " | " +
      basemap +
      " | " +
      attributions.join(" · ");
    const canvas = document.createElement("canvas");
    canvas.width = source.width;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Snapshot canvas is unavailable");
    ctx.font = "12px sans-serif";
    const lines: string[] = [];
    let line = "";
    for (const character of caption) {
      if (
        ctx.measureText(line + character).width > Math.max(1, canvas.width - 24)
      ) {
        lines.push(line);
        line = "";
      }
      line += character;
    }
    if (line) lines.push(line);
    canvas.height = source.height + 28 + lines.length * 18;
    ctx.fillStyle = "#111923";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(source, 0, 0);
    ctx.fillStyle = "#d3dde7";
    ctx.font = "12px sans-serif";
    lines.forEach((line, index) =>
      ctx.fillText(line, 12, source.height + 22 + index * 18),
    );
    return canvas.toDataURL("image/png");
  }
  destroy() {
    this.destroyed = true;
    clearInterval(this.timer);
    this.removeTick();
    this.handler.destroy();
    this.governor.destroy();
    this.presence?.destroy();
    this.imagery?.destroy();
    this.basemap.destroy();
    this.referenceLabels.destroy();
    this.viewer.destroy();
  }
}

function weatherLabel(o: Observation): string {
  const fields: Record<string, [string, string, number]> = {
    weather: ["temperature_c", "°C", 1],
    temperature: ["temperature_c", "°C", 1],
    wind: ["wind_speed_mps", "m/s", 1],
    precipitation: ["precipitation_mm", "mm", 1],
    pressure: ["pressure_pa", "hPa", 0.01],
    clouds: ["cloud_cover_percent", "%", 1],
  };
  const [key, unit, scale] = fields[o.layer];
  const value = o.properties?.[key];
  return (
    "Model " +
    (typeof value === "number"
      ? (value * scale).toFixed(1) + " " + unit
      : "unavailable")
  );
}
