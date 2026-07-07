import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// localStorage/sessionStorage are missing (or non-functional) in this test environment:
// Node >= 23 exposes an experimental `localStorage` global that is undefined without
// --localstorage-file, and the jsdom window here provides none either — so zustand's
// persist middleware crashes every store test with "Cannot read properties of undefined
// (reading 'setItem')". Install a functional in-memory Storage polyfill.
function createMemoryStorage(): Storage {
  let store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store = new Map();
    },
  };
}

function ensureStorage(name: 'localStorage' | 'sessionStorage') {
  let usable = false;
  try {
    const existing = window[name];
    if (existing) {
      existing.setItem('__storage_probe__', '1');
      existing.removeItem('__storage_probe__');
      usable = true;
    }
  } catch {
    usable = false;
  }
  if (!usable) {
    Object.defineProperty(window, name, { value: createMemoryStorage(), writable: true });
  }
  // Keep the bare global (Node's broken experimental shadow) pointing at the same instance.
  Object.defineProperty(globalThis, name, { value: window[name], writable: true });
}

ensureStorage('localStorage');
ensureStorage('sessionStorage');

// Cleanup after each test
afterEach(() => {
  cleanup();
});

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return [];
  }
  unobserve() {}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;
