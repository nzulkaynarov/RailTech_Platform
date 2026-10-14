import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { axe } from 'vitest-axe';

import { portalServer } from '@/mocks/server';

/** axe без нарушений на отрисованном экране (контейнер приложения + порталы диалогов в body). */
export async function expectNoAxeViolations(root: Element = document.body) {
  const results = await axe(root);
  expect(results.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
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
