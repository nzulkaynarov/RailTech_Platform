/**
 * Инвариант волны U2: **упавшее чтение не выглядит как «данных нет».**
 *
 * Аудит UI 2026-07-30: у мутаций единый обработчик ошибок был (`MutationCache.onError`),
 * у чтений — нет. Из-за этого ~35 справочников внутри селектов при отказе API молча
 * становились пустыми: пользователь не мог заполнить форму и не понимал почему.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { toast } from 'sonner';

import { queryClient } from '../queryClient';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

/** Отказ конкретного запроса через настоящий кэш — так же, как это происходит в приложении. */
async function failingQuery(queryKey: unknown[], error: unknown, meta?: Record<string, unknown>) {
  await queryClient
    .fetchQuery({ queryKey, queryFn: () => Promise.reject(error), retry: false, meta })
    .catch(() => undefined);
}

describe('глобальный обработчик ошибок чтения', () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
    queryClient.clear();
  });

  afterEach(() => {
    queryClient.clear();
  });

  it('переводит код ошибки бэкенда в человеческий текст', async () => {
    await failingQuery(['currencies'], { response: { status: 500, data: { detail: 'SERVER_ERROR' } } });
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it('несколько одновременных отказов сворачивает в ОДИН тост', async () => {
    // Страница с десятком справочников при обрыве сети обязана сказать об этом один раз.
    // Sonner заменяет тост с тем же `id`, поэтому проверяем, что id постоянный.
    await Promise.all([
      failingQuery(['currencies'], new Error('net')),
      failingQuery(['units'], new Error('net')),
      failingQuery(['categories'], new Error('net')),
    ]);
    const ids = vi.mocked(toast.error).mock.calls.map(([, options]) => (options as { id?: string })?.id);
    expect(ids.length).toBe(3);
    expect(new Set(ids).size).toBe(1);
    expect(ids[0]).toBeTruthy();
  });

  it('молчит про 401 — истёкшую сессию отрабатывает интерцептор axios', async () => {
    await failingQuery(['me'], { response: { status: 401, data: { detail: 'NOT_AUTHENTICATED' } } });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('запрос может отказаться от тоста, если показывает ошибку сам', async () => {
    await failingQuery(['deals'], new Error('boom'), { skipErrorToast: true });
    expect(toast.error).not.toHaveBeenCalled();
  });
});
