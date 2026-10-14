import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';

import i18n from '@/i18n';
import { resetMockPortal } from '@/mocks/handlers';
import { portalServer } from '@/mocks/server';
import { resetSessionBootstrap } from '@/session/session';

/**
 * Тесты идут с настоящим ru.json и моком портального API на границе HTTP (msw/node, те же
 * обработчики, что и dev-мок). Хранилища — в памяти: у jsdom и Node ≥ 23 их может не быть.
 */
function createMemoryStorage(): Storage {
  let store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, String(value)),
    removeItem: (key: string) => void store.delete(key),
    clear: () => {
      store = new Map();
    },
  };
}

for (const name of ['localStorage', 'sessionStorage'] as const) {
  Object.defineProperty(window, name, { value: createMemoryStorage(), configurable: true, writable: true });
  Object.defineProperty(globalThis, name, { value: window[name], configurable: true, writable: true });
}

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

beforeAll(() => portalServer.listen({ onUnhandledRequest: 'error' }));

beforeEach(async () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetMockPortal();
  resetSessionBootstrap();
  delete window.Telegram;
  document.documentElement.removeAttribute('style');
  document.documentElement.className = '';
  delete document.documentElement.dataset.mode;
  await i18n.changeLanguage('ru');
});

afterEach(() => {
  cleanup();
  portalServer.resetHandlers();
});

afterAll(() => portalServer.close());

// axe проверяет иконки-лигатуры через canvas, которого в jsdom нет: без заглушки — шум в выводе.
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement['getContext'];
