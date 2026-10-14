import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Cabinet — SPA без бэкенда (ADR-0004). В проде статика за Caddy на cabinet.*, `/api/portal/*`
// проксируется с того же домена на ERP (VITE_API_URL пустой → относительные запросы, cookie same-origin).
// В dev: `VITE_PORTAL_MOCK=1` включает MSW-мок портального API (src/mocks), иначе прокси dev-сервера
// ведёт на VITE_PORTAL_PROXY_TARGET (по умолчанию стенд ансамбля erp.localhost).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5175,
    // Туннели для проверки Mini App в тестовом боте (README): Telegram открывает только HTTPS.
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app'],
    proxy: {
      '/api/portal': {
        target: process.env.VITE_PORTAL_PROXY_TARGET ?? 'http://erp.localhost',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  esbuild: {
    drop: ['console', 'debugger'],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-i18n': ['i18next', 'react-i18next'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-radix': ['radix-ui'],
        },
      },
    },
  },
});
