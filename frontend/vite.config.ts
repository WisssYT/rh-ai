import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Same-origin /api proxy for the local demo. Backend URL is server-side config, not exposed as a secret.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: process.env.BACKEND_URL ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: process.env.BACKEND_URL ?? "http://127.0.0.1:8000" } },
  },
});
