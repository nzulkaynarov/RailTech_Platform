import react from "@vitejs/plugin-react";
import { msw } from "msw/vite";
import { defineConfig } from "vitest/config";

// В dev SPA открывается напрямую (`pnpm dev`, :5173) или через Caddy стенда (platform.localhost);
// прямой запуск проксирует /api в BFF. `pnpm dev:mock` (--mode mock) отвечает MSW, BFF не нужен.
const apiTarget = process.env["VITE_API_PROXY_TARGET"] ?? "http://localhost:8000";

export default defineConfig({
  // msw/vite (worker-only) отдаёт mockServiceWorker.js в dev-сервере и в сборке e2e (`vite build --mode mock`, W14-S2);
  // в боевой dist его нет, код мокирования — под import.meta.env.DEV.
  plugins: [
    react(),
    {
      ...msw({ mode: "worker-only" }),
      apply: (_config, { command, mode }) => command === "serve" || mode === "mock",
    },
  ],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: { "/api": apiTarget },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    testTimeout: 20_000,
    server: { deps: { inline: [/antd/, /@ant-design/] } },
  },
});
