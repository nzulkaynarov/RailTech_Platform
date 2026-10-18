import { defineConfig, configDefaults } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Сценарии экранов (ввод, диалоги, несколько запросов к моку) под параллельной нагрузкой дольше 5 с.
    testTimeout: 20_000,
    // Playwright browser specs live in e2e/ and run via `npm run test:e2e`,
    // not under vitest/jsdom — keep them out of the unit-test run.
    exclude: [...configDefaults.exclude, 'e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
      ],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
