import { describe, expect, it } from 'vitest';

import { resolveQuoteSendGate } from './useQuoteSendGate';
import type { Capabilities } from '@/store/userStore';

/**
 * Гейт отправки КП называет НАСТОЯЩУЮ причину (находка 5 прогона 20-08, замер 26-08).
 *
 * Продавцу с ОПЛАЧЕННОЙ подпиской, которому платформа явно отключила функцию, печаталось
 * «Отправка КП клиенту требует активной подписки», а кнопка вела в раздел подписки — где та
 * же подписка написана активной. Ложная причина плюс бесполезное действие: человек ходил по
 * кругу и не мог узнать, что произошло.
 *
 * Само правило не менялось: явный запрет платформы побеждает подписку (ADR-0006) — иначе
 * отключение права было бы бессмысленным. Изменилось то, КАК о нём сообщают.
 */

const BASE: Capabilities = {
  kyc_level: 'L2_VERIFIED',
  can_buy: true,
  can_sell: true,
  subscription_active: true,
  can_send_quotes: true,
  quote_send_is_demo: false,
  permissions: [],
  ai_daily_used: 0,
  ai_daily_cap: null,
  ai_daily_remaining: null,
};

const gate = (over: Partial<Capabilities>) => resolveQuoteSendGate({ ...BASE, ...over }, true);

describe('причина отказа в отправке КП', () => {
  it('не блокирует, когда всё на месте', () => {
    expect(gate({}).blocked).toBe(false);
  });

  it('запрет платформы называется своим именем, а не подпиской', () => {
    const result = gate({ can_send_quotes: false, quote_send_blocked_by_operator: true });

    expect(result.blocked).toBe(true);
    expect(result.reason).toBe('disabled_by_operator');
  });

  it('отсутствие подписки остаётся подпиской', () => {
    const result = gate({ can_send_quotes: false, subscription_active: false });

    expect(result.reason).toBe('subscription');
  });

  it('KYC важнее обоих: без уровня разговор о подписке преждевременен', () => {
    const result = gate({ kyc_level: 'L1_UNVERIFIED', can_send_quotes: false, quote_send_blocked_by_operator: true });

    expect(result.reason).toBe('kyc');
  });

  it('DEMO не подменяется запретом платформы', () => {
    const result = gate({ quote_send_is_demo: true, can_send_quotes: false });

    expect(result.reason).toBe('demo');
  });

  it('признак отсутствует у старого сервера — поведение прежнее, а не падение', () => {
    // Поле необязательное: витрина новее сервера в момент выката, и отсутствие признака не
    // должно превращаться в «запрет платформы».
    const result = gate({ can_send_quotes: false });

    expect(result.reason).toBe('subscription');
  });
});
