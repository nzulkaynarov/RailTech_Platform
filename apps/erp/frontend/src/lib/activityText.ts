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
 * Служебная метка в начале сохранённого текста («[MANUAL_MODE] Подписан договор…») нужна бэкенду для
 * сверки, но не человеку: в ленте печатается без неё (FIX-58, D-12).
 */
export function stripMarker(raw: string): string {
  return raw.replace(/^\[[A-Z0-9_]+\]\s*/, '');
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
  return stripMarker(raw);
}

export function activityTitle(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  if (!code) return stripMarker(entry.action);
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  return localizedOr(t, i18n, `activity.${code}.title`, params, entry.action);
}

export function activityDetail(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  if (!code) return entry.detail ?? '';
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  // Непустая причина включает i18next-контекст `reason`: у события может быть вариант
  // `detail_reason` («КП v2 — дорого»), а без причины печатается базовый `detail`. Так лента
  // не показывает висящее «—» и не падает в русский фолбэк из-за пустого плейсхолдера.
  const reason = params.reason;
  const withContext = typeof reason === 'string' && reason.trim() ? { ...params, context: 'reason' } : params;
  return localizedOr(t, i18n, `activity.${code}.detail`, withContext, entry.detail ?? '');
}
