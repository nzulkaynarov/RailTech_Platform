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
 * Шаблон по ключу с учётом ЦЕПОЧКИ языков, а не «сырого» тега.
 *
 * Браузер присылает региональный код (`en-US`, `ru-RU`), а ресурсы лежат под базовым (`en`,
 * `ru`): `nonExplicitSupportedLngs` заставляет i18next переводить правильно, но
 * `i18n.language` остаётся региональным. Запрос `getResource('en-US', …)` возвращал
 * undefined — и КАЖДАЯ строка журнала без параметров падала на текст, записанный в базу.
 *
 * В русском интерфейсе это было незаметно: запасной текст тоже русский. Дефект стал виден
 * только в английском — половина ленты оператора осталась русской (ux-review 03-08).
 */
function templateFor(i18n: I18nType, key: string): string | undefined {
  const chain = [i18n.resolvedLanguage, ...(i18n.languages ?? []), i18n.language].filter(Boolean);
  for (const lng of chain as string[]) {
    const template = i18n.getResource(lng, 'translation', key) as string | undefined;
    if (typeof template === 'string') return template;
  }
  return undefined;
}

/**
 * True when the stored template can be rendered with the given params: either the row
 * carries params, or the template needs none. Backfilled legacy rows (migration crm/0059)
 * have event_code but EMPTY params — interpolating a {{placeholder}} template with no
 * values would render holes ("КП v  на согласование"), so those fall back to the raw text.
 */
function renderable(i18n: I18nType, key: string, params: Record<string, unknown>): boolean {
  if (Object.keys(params).length > 0) return true;
  const template = templateFor(i18n, key);
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
