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

export function activityTitle(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  if (code && i18n.exists(`activity.${code}.title`) && renderable(i18n, `activity.${code}.title`, params)) {
    return t(`activity.${code}.title`, params);
  }
  return entry.action;
}

export function activityDetail(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  if (code && i18n.exists(`activity.${code}.detail`) && renderable(i18n, `activity.${code}.detail`, params)) {
    return t(`activity.${code}.detail`, params);
  }
  return entry.detail ?? '';
}
