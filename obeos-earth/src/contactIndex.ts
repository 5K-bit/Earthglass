import type { Observation } from "./contracts";
import { isNewer } from "./controlApi";

/** Bounded entity index. Selection survives live refreshes; replay replaces its time slice exactly. */
export function reconcile(
  store: Map<string, Observation>,
  values: Observation[],
  replace = false,
  preserve: string[] = [],
  capacity = 20000,
) {
  const protectedIds = new Set(preserve);
  const removed: string[] = [];
  const updated: Observation[] = [];
  if (replace) {
    const incoming = new Set(values.map((o) => o.entity_id));
    for (const id of store.keys())
      if (!incoming.has(id) && !protectedIds.has(id)) {
        store.delete(id);
        removed.push(id);
      }
  }
  for (const value of values) {
    const previous = store.get(value.entity_id);
    if (!replace && !isNewer(value, previous)) continue;
    store.set(value.entity_id, value);
    if (
      !previous ||
      previous.observed_at !== value.observed_at ||
      JSON.stringify(previous.position) !== JSON.stringify(value.position)
    )
      updated.push(value);
  }
  for (const id of store.keys()) {
    if (store.size <= capacity) break;
    if (!protectedIds.has(id)) {
      store.delete(id);
      removed.push(id);
    }
  }
  return { updated, removed };
}
