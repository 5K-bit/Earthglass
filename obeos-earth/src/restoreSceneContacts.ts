import type { Observation } from "./contracts";
import type { ObservationPage, SceneState } from "./controlApi";

/** Restore scene-owned contacts separately from the viewport, including during replay. */
export async function restoreSceneContacts(
  observations: Observation[],
  scene: SceneState | null,
  fetchPage: (path: string) => Promise<ObservationPage>,
): Promise<Observation[]> {
  if (!scene || scene.active_investigation_id) return observations;
  const present = new Set(observations.map((o) => o.entity_id));
  const ids = [...new Set([
    scene.selected_entity_id,
    scene.tracked_entity_id,
    scene.camera.entity_id,
  ].filter((id): id is string => Boolean(id)))].filter((id) => !present.has(id));
  const pages = await Promise.all(ids.map((id) => {
    const query = new URLSearchParams({ entity_id: id, limit: "1" });
    if (scene.timeline.at) query.set("at", scene.timeline.at);
    return fetchPage("/api/v2/observations?" + query);
  }));
  return [...observations, ...pages.flatMap((page, index) =>
    page.observations.filter((o) => o.entity_id === ids[index]).slice(0, 1),
  )];
}
