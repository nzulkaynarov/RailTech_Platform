/**
 * Ключ подписи операторского права. Отдельный модуль — Fast Refresh (файл-страница
 * не должен экспортировать ничего, кроме компонентов).
 */

/**
 * i18next uses '.' as its key separator, but operator-permission codes contain
 * dots (e.g. "kyc.verify"). Map the dotted code to a single-segment key under
 * `operatorPermissions` so it resolves against the (nested) locale object.
 */
export function operatorPermLabelKey(code: string): string {
  return `operatorPermissions.${code.replace(/\./g, '_')}`;
}
