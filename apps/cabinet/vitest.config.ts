import path from 'node:path';
import { defineConfig, configDefaults } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    exclude: [...configDefaults.exclude, 'e2e/**'],
    css: false,
    // Имя бота для ссылок t.me в тестах (в сборке — VITE_BOT_USERNAME из окружения).
    env: { VITE_BOT_USERNAME: 'railtech_test_bot' },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
