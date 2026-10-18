import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// В dev фронт открывается через Caddy (http://localhost), который проксирует
// /api, /health, /ready на api. Прямой запуск `pnpm dev` проксирует их сам.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
      "/ready": apiTarget,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Сценарии экранов (Ant Design, несколько запросов) под параллельной нагрузкой дольше 5 с.
    testTimeout: 20_000,
    // Refine импортирует react-router как CJS; инлайн убирает двойную копию контекста роутера.
    server: { deps: { inline: [/@refinedev/, /antd/, /@ant-design/] } },
  },
});
