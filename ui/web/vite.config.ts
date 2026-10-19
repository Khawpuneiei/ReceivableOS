import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

// The browser only ever calls /api. In live mode this server forwards /api to the orchestrator and adds the
// caller token here, on the server side, so ORCHESTRATOR_TOKEN never reaches the page or the bundle.
export default defineConfig(({ mode }) => {
  // The repo root .env plus the shell environment (the shell wins), all keys: read here, never bundled.
  const env = loadEnv(mode, "../..", "");
  const target = (env.ORCHESTRATOR_URL || "http://localhost:8000").replace(/\/+$/, "");
  const token = (env.ORCHESTRATOR_TOKEN || "").trim();
  const proxy = {
    "/api": {
      target,
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api/, ""),
      headers: token ? { "X-Orchestrator-Token": token } : {},
    },
  };
  return {
    plugins: [react()],
    define: { __UI_MODE__: JSON.stringify(env.UI_MODE === "live" ? "live" : "fixtures") },
    // ui/fixtures (saved responses) and data/invoices/demo (the demo PDFs) sit outside this folder.
    server: { port: 3001, strictPort: true, proxy, fs: { allow: ["..", "../../data/invoices/demo"] } },
    preview: { port: 3001, strictPort: true, proxy },
    test: { environment: "jsdom", include: ["tests/**/*.test.{ts,tsx}"] },
  };
});
