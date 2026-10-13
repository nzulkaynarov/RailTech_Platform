import { describe, expect, it } from 'vitest';

import { countAccessLogBuckets, totalOfBuckets } from './accessLogBuckets';
import type { AdminAccessLogEntry } from '@/api/adminApi';

/**
 * Плитки журнала доступа сходятся с лентой (находка 75 прогона 20-08).
 *
 * Замер: плитки показывали 0 + 1 + 17 = 18 при 20 строках в ленте. Две записи об аварийном
 * доступе с ИСТЁКШИМ сроком не попадали ни в один счётчик — в «активные» их не пускал
 * `is_active`, из «остальных административных» вычёркивал `!is_break_glass`.
 */

function entry(over: Partial<AdminAccessLogEntry>): AdminAccessLogEntry {
  return {
    id: 1,
    action: 'что-то сделал',
    detail: '',
    level: 'INFO',
    reason: '',
    entity_type: 'accounts.company',
    entity_id: 1,
    user_email: 'op@test.uz',
    user_name: 'Оператор',
    timestamp: '2026-08-20T10:00:00Z',
    expires_at: null,
    is_break_glass: false,
    is_force_override: false,
    is_active: false,
    ...over,
  };
}

describe('счётчики журнала доступа', () => {
  it('истёкший аварийный доступ считается, а не исчезает', () => {
    const items = [
      entry({ id: 1, is_break_glass: true, is_active: true }),
      entry({ id: 2, is_break_glass: true, is_active: false }),
      entry({ id: 3, is_break_glass: true, is_active: false }),
    ];

    const buckets = countAccessLogBuckets(items);

    expect(buckets.activeBreakGlass).toBe(1);
    expect(buckets.expiredBreakGlass).toBe(2);
  });

  it('сумма плиток равна числу строк ленты — иначе по ним нельзя судить о содержимом', () => {
    const items = [
      entry({ id: 1, is_break_glass: true, is_active: true }),
      entry({ id: 2, is_break_glass: true, is_active: false }),
      entry({ id: 3, is_force_override: true }),
      entry({ id: 4 }),
      entry({ id: 5 }),
    ];

    expect(totalOfBuckets(countAccessLogBuckets(items))).toBe(items.length);
  });

  it('запись, помеченная И аварийной, И override, считается ОДИН раз', () => {
    // Корзины пересекались: такая строка попадала и в break-glass, и в force-override,
    // и сумма плиток превышала ленту — врала в другую сторону.
    const items = [entry({ id: 1, is_break_glass: true, is_active: true, is_force_override: true })];

    const buckets = countAccessLogBuckets(items);

    expect(totalOfBuckets(buckets)).toBe(1);
    expect(buckets.activeBreakGlass).toBe(1);
    expect(buckets.forceOverrides).toBe(0);
  });

  it('новый вид события уходит в «остальные административные», а не теряется', () => {
    // Урок прошлой правки этого же места: счётчик «всё остальное» обязан существовать,
    // иначе первое же новое событие выпадет из сводки.
    const items = [entry({ id: 1, event_code: 'admin.emergency.verify_kyc' })];

    expect(countAccessLogBuckets(items).adminActions).toBe(1);
    expect(totalOfBuckets(countAccessLogBuckets(items))).toBe(1);
  });

  it('пустая лента даёт нули, а не падение', () => {
    expect(totalOfBuckets(countAccessLogBuckets([]))).toBe(0);
  });
});
