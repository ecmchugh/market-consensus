import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The dashboard is a static SPA that talks to the FastAPI backend over HTTP.
// In dev we proxy /api -> localhost:8000 so there are no CORS surprises; in
// production the frontend hits VITE_API_BASE directly (see src/api/client.ts).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
