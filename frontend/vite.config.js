import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the page is served by Vite (port 5173) and API calls are forwarded
// to FastAPI on port 8000, so the browser sees one origin and no CORS is needed.
const API = "http://127.0.0.1:8000";

// Tests show message times: run them in UTC so they pass on any machine.
if (process.env.VITEST) process.env.TZ = "UTC";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/chat": API,
      "/health": API,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.js",
  },
});
