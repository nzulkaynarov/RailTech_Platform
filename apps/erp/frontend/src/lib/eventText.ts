import type { i18n as I18nType, TFunction } from 'i18next';

import {
  approvalParticipationLabelKey,
  companyTypeLabelKey,
  dealStageLabelKey,
  kycLevelLabelKey,
} from './codes';

/**
 * Общая механика двух лент — журнала сделки (`activityText`) и уведомлений
 * (`notificationText`).
 *
 * Ленты — близнецы: бэкенд пишет машинный `event_code` + `event_params`, человеческий текст
 * собирается на языке ЗРИТЕЛЯ. Механика жила в двух копиях, и это стоило дефекта: региональный
 * тег языка починили в одной копии, а во второй он остался (ux-review 03-08). Поэтому обе
 * тонкости — разрешение языка и подписи к кодовым параметрам — живут здесь в одном экземпляре.
 */

/**
 * Шаблон по ключу с учётом ЦЕПОЧКИ языков, а не «сырого» тега.
 *
 * Браузер присылает региональный код (`en-US`, `ru-RU`), а ресурсы лежат под базовым (`en`,
 * `ru`): `nonExplicitSupportedLngs` заставляет i18next переводить правильно, но
 * `i18n.language` остаётся региональным. Запрос `getResource('en-US', …)` возвращал
 * undefined — и КАЖДАЯ строка без параметров падала на текст, записанный в базу.
 */
export function templateFor(i18n: I18nType, key: string): string | undefined {
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
export function renderable(i18n: I18nType, key: string, params: Record<string, unknown>): boolean {
  if (Object.keys(params).length > 0) return true;
  const template = templateFor(i18n, key);
  return typeof template === 'string' && !template.includes('{{');
}

/**
 * Параметры, которые приходят КОДОМ, а подпись к ним подбирается ЗДЕСЬ.
 *
 * Событие пишется в момент действия, а читают его позже и, вообще говоря, на другом языке.
 * Пока сервер клал в параметры отображаемое имя («Черновик», «Руководитель»), оно замерзало
 * на языке ТОГО, кто действовал: в английской ленте оператора стояло
 * «Deal #16: Черновик → Открытый RFQ» и «Step approved (Руководитель)».
 *
 * Канон — ARCH-05 «по проводам коды, слова на краях» (бенчмарк: Stripe шлёт `status`,
 * локализует витрина; Odoo хранит `state`, переводит `_description`). Здесь и есть тот край.
 *
 * `param` — что заполняем (это имя стоит в шаблоне); `source` — откуда берём код. Они
 * совпадают, когда сервер и раньше присылал код, а подпись к нему просто не подбиралась
 * (статус отгрузки). Нет кода (СТАРЫЕ строки) или код неизвестен —
 * значение остаётся как было: лента ничего не теряет.
 */
const CODED_PARAMS: ReadonlyArray<{ param: string; source: string; labelKey: (code: string) => string }> = [
  { param: 'from_stage', source: 'from_stage_code', labelKey: dealStageLabelKey },
  { param: 'to_stage', source: 'to_stage_code', labelKey: dealStageLabelKey },
  { param: 'from_status', source: 'from_status_code', labelKey: kycLevelLabelKey },
  { param: 'to_status', source: 'to_status_code', labelKey: kycLevelLabelKey },
  { param: 'participation', source: 'participation_code', labelKey: approvalParticipationLabelKey },
  { param: 'role_name', source: 'role_code', labelKey: companyTypeLabelKey },
  { param: 'role_code', source: 'role_code', labelKey: companyTypeLabelKey },
  { param: 'field', source: 'field', labelKey: contractWordingFieldLabelKey },
  // Стандартная редакция пункта договора — не пользовательский заголовок, а состояние.
  { param: 'variant', source: 'variant_code', labelKey: (code) => (code === 'STANDARD' ? 'contractsPage.wording.standard' : '') },
  // Уведомления: сервер шлёт код прямо в параметре с тем же именем.
  { param: 'stage_code', source: 'stage_code', labelKey: dealStageLabelKey },
  { param: 'status_code', source: 'status_code', labelKey: (code) => `fulfillmentPage.status.${code}` },
  { param: 'level_code', source: 'level_code', labelKey: kycLevelLabelKey },
];

/** i18n-ключ подписи пункта договора по машинному имени поля формулировки. */
function contractWordingFieldLabelKey(field: string): string {
  const known: Record<string, string> = {
    contract_acceptance_text: 'contractsPage.wording.acceptance',
    contract_liability_text: 'contractsPage.wording.liability',
    contract_extra_terms_text: 'contractsPage.wording.extraTerms',
  };
  return known[field] ?? '';
}

/**
 * Подставить подписи к кодовым параметрам, не трогая остальные. Если словарь не знает код,
 * значение остаётся прежним — сам код информативнее пустоты и сразу виден как пробел в словаре.
 */
export function localizeParams(
  t: TFunction,
  i18n: I18nType,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const localized = { ...params };
  for (const { param, source, labelKey } of CODED_PARAMS) {
    const code = params[source];
    if (typeof code !== 'string' || !code) continue;
    const key = labelKey(code);
    if (key && i18n.exists(key)) localized[param] = t(key);
  }
  return localized;
}
