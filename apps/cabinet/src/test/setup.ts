import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest';
import { toast } from 'sonner';

import i18n from '@/i18n';
import { resetMockPortal } from '@/mocks/handlers';
import { portalServer } from '@/mocks/server';
import { resetSessionBootstrap } from '@/session/session';

// findBy*/waitFor ждут по умолчанию 1 с — на раннере CI (2 vCPU) и под параллельной нагрузкой сценарий
// экрана с несколькими запросами к моку не успевает; 5 с — с запасом, тестовый таймаут — 20 с (vitest.config).
configure({ asyncUtilTimeout: 5_000 });

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

// Загрузка файла в тестах: fetch (undici) собирает multipart-тело и разбирает его в обработчике MSW своим классом File,
// а jsdom подменяет глобальный File своим — undici отвергает чужой класс (`webidl.is.File`). Возвращаем File из Node.
// (имя модуля — в переменной: типы Node в сборку Cabinet не подключены)
const nodeBuffer = 'node:buffer';
const { File: NodeFile } = (await import(/* @vite-ignore */ nodeBuffer)) as { File: typeof File };
Object.defineProperty(globalThis, 'File', { value: NodeFile, configurable: true, writable: true });
// То же с FormData: jsdom-версия не принимает File из Node (превращает его в строку). Класс undici берём у Response.
const NodeFormData = (await new Response(new URLSearchParams()).formData()).constructor as typeof FormData;
Object.defineProperty(globalThis, 'FormData', { value: NodeFormData, configurable: true, writable: true });

beforeAll(() => portalServer.listen({ onUnhandledRequest: 'error' }));

/**
 * «Сегодня» фикстур — 2026-10-14 в Ташкенте: просрочка счетов и срок действия КП считаются от него.
 * Подменяется только `Date` — таймеры настоящие (MSW, React Query, анимации Radix).
 */
const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['Date'], now: FIXTURE_NOW });
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

/**
 * Охрана «человеческого текста» (СЦ-7): тест падает, если на экране остался сырой ключ i18n или код, число или дата в
 * машинном виде. Те же правила — в Платформе (`apps/platform/web/src/test/setup.ts`).
 * Сканируется текст страницы до `cleanup()`; допустимое — только в явном списке ниже, с причиной.
 */
const missingKeys = new Set<string>();
i18n.options.saveMissing = true;
i18n.options.missingKeyHandler = (_languages, namespace, key) => {
  missingKeys.add(`${namespace}:${key}`);
};

const RAW_PATTERNS: Array<{ name: string; re: RegExp }> = [
  { name: 'raw i18n key', re: /\b(?:pages|widgets|common|errors|roles|status|nav)\.[A-Za-z]+(?:\.[A-Za-z0-9_]+)+/ },
  { name: 'ISO date', re: /\b\d{4}-\d{2}-\d{2}(?:T|\b)/ },
  { name: 'raw decimal amount', re: /\b\d{5,}\.\d{2}\b/ },
  { name: 'record number "#123"', re: /#\d+/ },
];

/**
 * Допустимые попадания — не СЦ-7, вынесены в «Хвосты» PR (лид переносит в inbox плана). Подстрока текста страницы → причина.
 * Новое сюда не добавлять: исправить экран.
 */
const HUMAN_TEXT_ALLOW: Array<{ name: string; text: RegExp; why: string }> = [
  // Контекст обязателен: любой другой «#N» на экране по-прежнему роняет тест. Слово — pages.partnerOrders.receiptPrefix (ru/en/uz).
  { name: 'record number "#123"', text: /(?:Приёмка|Receipt|Qabul) #\d+$/, why: '«Приёмка #8301» (partnerOrders, карточка заказа) — отдельная находка, не СЦ-7, в «Хвосты»' },
  { name: 'raw decimal amount', text: /^1500000\.50$/, why: 'подсказка формата ввода суммы в «Я оплатил» (pages.invoices.proofDialog.amountHint) — пример того, что набрать; не СЦ-7' },
];

function humanTextProblems(text: string): string[] {
  const problems: string[] = [];
  for (const { name, re } of RAW_PATTERNS) {
    for (const match of text.matchAll(new RegExp(re.source, 'g'))) {
      const hit = match[0];
      // Allow-list смотрит на хит вместе с 12 символами слева — так исключение привязано к контексту, а не к шаблону.
      const withContext = text.slice(Math.max(0, (match.index ?? 0) - 12), (match.index ?? 0) + hit.length);
      if (HUMAN_TEXT_ALLOW.some((rule) => rule.name === name && (rule.text.test(hit) || rule.text.test(withContext)))) continue;
      problems.push(`${name}: ${hit}`);
    }
  }
  return problems;
}

afterEach(() => {
  const problems = humanTextProblems(document.body.textContent ?? '');
  const missing = Array.from(missingKeys);
  missingKeys.clear();
  if (missing.length > 0) problems.push(...missing.map((key) => `missing i18n key: ${key}`));
  // Вся уборка — до ошибки охраны, иначе переопределения мока утекают в соседние тесты.
  cleanup();
  // Очередь тостов sonner — состояние модуля: без сброса тост прошлого теста всплывает в следующем.
  toast.dismiss();
  portalServer.resetHandlers();
  portalServer.events.removeAllListeners();
  vi.useRealTimers();
  if (problems.length > 0) throw new Error(`Human text guard: ${[...new Set(problems)].join('; ')}`);
});

// Radix Checkbox меряет себя через ResizeObserver, которого в jsdom нет.
if (!('ResizeObserver' in window)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(window, 'ResizeObserver', { value: ResizeObserverStub, configurable: true, writable: true });
  Object.defineProperty(globalThis, 'ResizeObserver', { value: ResizeObserverStub, configurable: true, writable: true });
}

// Radix Select и Tooltip требуют методы указателя и скролла, которых нет в jsdom.
if (!window.HTMLElement.prototype.hasPointerCapture) {
  window.HTMLElement.prototype.hasPointerCapture = () => false;
}
if (!window.HTMLElement.prototype.setPointerCapture) {
  window.HTMLElement.prototype.setPointerCapture = () => {};
}
if (!window.HTMLElement.prototype.releasePointerCapture) {
  window.HTMLElement.prototype.releasePointerCapture = () => {};
}
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}

// Сохранение файла: в jsdom нет object URL и навигации по ссылке-скачиванию.
window.URL.createObjectURL = vi.fn(() => 'blob:cabinet-test');
window.URL.revokeObjectURL = vi.fn();
HTMLAnchorElement.prototype.click = vi.fn();

afterAll(async () => {
  portalServer.close();
  // sonner убирает тост таймером (200 мс) уже после размонтирования; если файл тестов кончился
  // раньше, таймер срабатывает без jsdom — «window is not defined» и красный прогон. Дожидаемся.
  await new Promise((resolve) => setTimeout(resolve, 300));
});

// axe проверяет иконки-лигатуры через canvas, которого в jsdom нет: без заглушки — шум в выводе.
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement['getContext'];
