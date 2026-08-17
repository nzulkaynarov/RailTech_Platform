import type { i18n as I18nType, TFunction } from 'i18next';

import { localizeParams, renderable } from './eventText';

/**
 * Structured-event rendering for ActivityLog feeds (spec-timeline-i18n 2026-07-12).
 *
 * Backend writes a machine `event_code` + `event_params`; the human-readable text is
 * assembled here in the viewer's locale (GitHub/Stripe-style timeline). When a row has
 * no `event_code`, or no `activity.<code>.*` key exists (legacy rows / admin free-form
 * actions), we fall back to the raw RU `action`/`detail` the producer stored.
 *
 * Разрешение языка и подписи к кодовым параметрам — общие с лентой уведомлений и живут в
 * `eventText.ts`: механика в двух копиях уже стоила дефекта (см. комментарий там).
 */
export interface ActivityLike {
  event_code?: string | null;
  event_params?: Record<string, unknown> | null;
  action: string;
  detail?: string;
}

/**
 * `exists()` ОБЯЗАН получать те же params, что и `t()`.
 *
 * У событий со счётчиком (`deal.routed`, `deal.submitted`) простого ключа `detail` нет —
 * есть только формы `detail_one` / `detail_other` (и `_few`/`_many` для русского). Без
 * `count` в опциях i18next ищет ровно `…detail`, не находит и возвращает false: гейт
 * проваливался, и лента печатала «сырое» поле, которое бэкенд записал ПО-РУССКИ. В русском
 * интерфейсе подмена невидима (фолбэк тоже русский), а в английском рядом с переведённым
 * заголовком стояло «Deal #19: 1 продавцу» — найдено прогоном клина глазами 14-08.
 */
function localizedOr(t: TFunction, i18n: I18nType, key: string, params: Record<string, unknown>, raw: string): string {
  if (i18n.exists(key, params) && renderable(i18n, key, params)) return t(key, params);
  return raw;
}

export function activityTitle(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  if (!code) return entry.action;
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  return localizedOr(t, i18n, `activity.${code}.title`, params, entry.action);
}

export function activityDetail(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  if (!code) return entry.detail ?? '';
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  return localizedOr(t, i18n, `activity.${code}.detail`, params, entry.detail ?? '');
}
