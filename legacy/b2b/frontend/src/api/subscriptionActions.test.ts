import { beforeEach, describe, expect, it, vi } from 'vitest';

// `accountsApi` берёт ИМЕНОВАННЫЙ экспорт `apiClient` — мок обязан отдавать именно его,
// иначе вызов уходит в настоящий axios и тест падает на сети, а не на предмете проверки.
vi.mock('./client', () => {
  const client = { post: vi.fn(), patch: vi.fn(), get: vi.fn(), delete: vi.fn() };
  return { apiClient: client, default: client };
});

import { apiClient } from './client';
import { accountsApi } from './accountsApi';

/**
 * Причина приостановки доезжает до сервера (находка 42 прогона 20-08, замер 26-08).
 *
 * Диалог помечен `requireReason`, собирал причину и передавал её в колбэк — а вызов уходил
 * БЕЗ ТЕЛА, и до сервера она не доезжала. Барьер стоял, значение выбрасывала витрина.
 *
 * Цена дефекта выросла уже ПОСЛЕ прогона: с #611 сервер кладёт причину в письмо арендатору и
 * в поле, которое тот видит у себя. То есть отключённый продавец получал письмо с пустым
 * объяснением — ровно то, ради чего волну и делали.
 */
describe('приостановка подписки', () => {
  beforeEach(() => {
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: 1, status: 'SUSPENDED' } } as never);
  });

  it('шлёт причину телом запроса', async () => {
    await accountsApi.suspendSubscription(7, 'Неоплата за два месяца');

    expect(apiClient.post).toHaveBeenCalledWith('accounts/subscriptions/7/suspend/', {
      reason: 'Неоплата за два месяца',
    });
  });

  it('причина — обязательный параметр, её нельзя забыть молча', async () => {
    // Гарантию держит СИГНАТУРА, а не дефолт: раньше `reason = ''` разрешал ровно то, что
    // диалог запрещает, и забытый аргумент компилировался, отправляя пустое объяснение в
    // письмо арендатору. Проверяем, что пустая строка доезжает как есть — решение о том,
    // обязательна ли причина, принимает сервер.
    await accountsApi.suspendSubscription(7, '');

    expect(apiClient.post).toHaveBeenCalledWith('accounts/subscriptions/7/suspend/', { reason: '' });
  });

  it('активация причины не требует — письма она не порождает', async () => {
    await accountsApi.activateSubscription(7);

    expect(apiClient.post).toHaveBeenCalledWith('accounts/subscriptions/7/activate/');
  });
});
