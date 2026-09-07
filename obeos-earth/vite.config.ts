import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const cesiumSource = "node_modules/cesium/Build/Cesium";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  publicDir: false,
  define: {
    CESIUM_BASE_URL: JSON.stringify(
      command === "serve" ? "/node_modules/cesium/Build/Cesium" : "/cesium"
    )
  },
  server: {
    port: 5173,
    strictPort: true
  },
  preview: {
    port: 4173,
    strictPort: true
  }
}));
