import type { AdminAccessLogEntry } from '@/api/adminApi';

/**
 * Разбор ленты журнала доступа на корзины для плиток.
 *
 * Замер 20-08: плитки показывали 0 + 1 + 17 = 18, а в ленте под ними было 20 строк. Две записи
 * об аварийном доступе с ИСТЁКШИМ сроком не попадали ни в один счётчик — в «активные» их не
 * пускал `is_active`, из «остальных административных» вычёркивал `!is_break_glass`. По плиткам
 * этих записей как будто не существовало, а читают журнал именно постфактум, когда срок уже
 * истёк.
 *
 * Корзины НЕ ПЕРЕСЕКАЮТСЯ и покрывают ленту целиком — сумма равна числу строк. Это и есть
 * условие, при котором по подписанным итогам можно судить о содержимом (Odoo O-AGGREGATE);
 * без него плитка остаётся украшением. Держит связку тест `accessLogBuckets.test.ts`.
 *
 * Живёт ОТДЕЛЬНЫМ модулем, а не рядом с компонентом: хелпер в файле-компоненте ломает
 * Fast Refresh (правило проекта) и не проверяется отдельно от разметки.
 */
export interface AccessLogBuckets {
  activeBreakGlass: number;
  expiredBreakGlass: number;
  forceOverrides: number;
  adminActions: number;
}

export function countAccessLogBuckets(entries: readonly AdminAccessLogEntry[]): AccessLogBuckets {
  const buckets: AccessLogBuckets = {
    activeBreakGlass: 0,
    expiredBreakGlass: 0,
    forceOverrides: 0,
    adminActions: 0,
  };

  for (const entry of entries) {
    if (entry.is_break_glass) {
      // Аварийный доступ учитывается ВСЕГДА — вопрос только в том, действует ли он ещё.
      if (entry.is_active) buckets.activeBreakGlass += 1;
      else buckets.expiredBreakGlass += 1;
    } else if (entry.is_force_override) {
      buckets.forceOverrides += 1;
    } else {
      buckets.adminActions += 1;
    }
  }

  return buckets;
}

/** Сумма корзин. Существует ради проверки «плитки сходятся с лентой». */
export function totalOfBuckets(buckets: AccessLogBuckets): number {
  return buckets.activeBreakGlass + buckets.expiredBreakGlass + buckets.forceOverrides + buckets.adminActions;
}
