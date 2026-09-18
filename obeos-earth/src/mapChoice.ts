export type Basemap = "auto" | "offline" | "satellite" | "streets";
export type MapStatus = {
  mode: Exclude<Basemap, "auto">;
  state: "loading" | "ready" | "offline" | "fallback";
  message: string;
};
export function resolveBasemap(
  preference: Basemap,
  offline: boolean,
): Exclude<Basemap, "auto"> {
  return offline ? "offline" : preference === "auto" ? "satellite" : preference;
}
