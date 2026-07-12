import type { i18n as I18nType, TFunction } from 'i18next';

/**
 * Structured-event rendering for ActivityLog feeds (spec-timeline-i18n 2026-07-12).
 *
 * Backend writes a machine `event_code` + `event_params`; the human-readable text is
 * assembled here in the viewer's locale (GitHub/Stripe-style timeline). When a row has
 * no `event_code`, or no `activity.<code>.*` key exists (legacy rows / admin free-form
 * actions), we fall back to the raw RU `action`/`detail` the producer stored.
 */
export interface ActivityLike {
  event_code?: string | null;
  event_params?: Record<string, unknown> | null;
  action: string;
  detail?: string;
}

/**
 * True when the stored template can be rendered with the given params: either the row
 * carries params, or the template needs none. Backfilled legacy rows (migration crm/0059)
 * have event_code but EMPTY params — interpolating a {{placeholder}} template with no
 * values would render holes ("КП v  на согласование"), so those fall back to the raw text.
 */
function renderable(i18n: I18nType, key: string, params: Record<string, unknown>): boolean {
  if (Object.keys(params).length > 0) return true;
  const template = i18n.getResource(i18n.language, 'translation', key) as string | undefined;
  return typeof template === 'string' && !template.includes('{{');
}

export function activityTitle(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  const params = { ...(entry.event_params ?? {}) };
  if (code && i18n.exists(`activity.${code}.title`) && renderable(i18n, `activity.${code}.title`, params)) {
    return t(`activity.${code}.title`, params);
  }
  return entry.action;
}

export function activityDetail(t: TFunction, i18n: I18nType, entry: ActivityLike): string {
  const code = entry.event_code;
  const params = { ...(entry.event_params ?? {}) };
  if (code && i18n.exists(`activity.${code}.detail`) && renderable(i18n, `activity.${code}.detail`, params)) {
    return t(`activity.${code}.detail`, params);
  }
  return entry.detail ?? '';
}
