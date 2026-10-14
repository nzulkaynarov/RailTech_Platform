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
    // Сценарии экранов (ввод, диалоги, несколько запросов к моку) под параллельной нагрузкой дольше 5 с.
    testTimeout: 20_000,
    // Имя бота для ссылок t.me в тестах (в сборке — VITE_BOT_USERNAME из окружения).
    // Адрес CRM формы «Я новый клиент» — мок MSW отвечает на любой origin.
    env: { VITE_BOT_USERNAME: 'railtech_test_bot', VITE_CRM_URL: 'http://crm.test' },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
