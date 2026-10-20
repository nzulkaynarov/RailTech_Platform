import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { axe } from 'vitest-axe';

import { portalServer } from '@/mocks/server';

/**
 * Правила axe для jsdom. `color-contrast` отключён: jsdom не считает раскладку и цвета (в `css: false` стилей Tailwind нет),
 * правило там ничего не проверяет, а контраст токенов закрыт `packages/ui-tokens` и осмотром глазами
 * (README axe-core, «JSDOM»: `color-contrast` в jsdom не работает, рекомендовано выключать).
 */
const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false } } };

/**
 * Что проверять: содержимое экрана (`<main>`) и открытые диалоги (порталы в body), а не весь документ.
 * Оболочку (меню, шапку, тосты) проверяет один тест `shell.test.tsx` по всему приложению. Причина — цена: первый
 * запуск axe в файле тратит ~2,5 с на компиляцию селекторов в jsdom, и эта цена растёт с числом узлов (на меню и
 * иконках оболочки уходило две трети); на медленном раннере CI она вылезала за таймаут теста.
 */
function auditTargets(): Element[] {
  const main = document.querySelector('main');
  if (!main) return [document.body];
  return [main, ...Array.from(document.querySelectorAll('[role="dialog"]'))];
}

/** axe без нарушений на экране: `root` — явный блок, по умолчанию — `<main>` и диалоги (см. `auditTargets`). */
export async function expectNoAxeViolations(root?: Element) {
  const violations: string[] = [];
  for (const target of root ? [root] : auditTargets()) {
    const results = await axe(target, AXE_OPTIONS);
    violations.push(...results.violations.map((violation) => `${violation.id}: ${violation.help}`));
  }
  expect(violations).toEqual([]);
}

/** Дождаться заголовка экрана (h1). */
export function heading(name: string | RegExp) {
  return screen.findByRole('heading', { level: 1, name });
}

/** Подменить ответ портала ошибкой `{"detail": CODE}` (409 «уже принято», 403…). */
export function failWith(method: 'get' | 'post' | 'put', path: string, status: number, detail: string) {
  portalServer.use(http[method](`*/api/portal/v1${path}`, () => HttpResponse.json({ detail }, { status })));
}

/** Тело последнего запроса на путь — проверка, что ушло в ERP ровно по контракту. */
export function captureBody(path: string): { current: unknown } {
  const captured: { current: unknown } = { current: undefined };
  portalServer.events.on('request:start', async ({ request }) => {
    if (new URL(request.url).pathname.endsWith(path) && request.method !== 'GET') {
      captured.current = await request.clone().json();
    }
  });
  return captured;
}

/**
 * Журнал запросов к порталу: `METHOD /path` в порядке отправки — проверка, что действие ушло в ERP
 * (и что кнопка без запроса ничего не сделала). Тела не читает: у `request-code`, приёмки строки их нет.
 */
export function requestLog(): string[] {
  const log: string[] = [];
  portalServer.events.on('request:start', ({ request }) => {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/portal/v1/')) log.push(`${request.method} ${url.pathname.replace('/api/portal/v1', '')}`);
  });
  return log;
}

/** Тело последнего запроса на путь как текст: `''` — тела нет (приёмка акта без скана). `null` — запроса не было. */
export function captureText(path: string): { current: string | null } {
  const captured: { current: string | null } = { current: null };
  portalServer.events.on('request:start', async ({ request }) => {
    if (new URL(request.url).pathname.endsWith(path) && request.method !== 'GET') {
      captured.current = await request.clone().text();
    }
  });
  return captured;
}
