import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "cesium/Build/Cesium/Widgets/widgets.css";
import BroadcastStudio from "./BroadcastStudio";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BroadcastStudio />
  </StrictMode>,
);
