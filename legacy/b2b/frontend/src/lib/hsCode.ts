/**
 * Форматирование кода ТН ВЭД. Вынесено из компонента поля — см. pageLabels.ts.
 */

export function formatHSCode(code: string): string {
  const digits = (code || '').replace(/\D/g, '');
  if (digits.length <= 4) return digits;
  return [digits.slice(0, 4), digits.slice(4, 6), digits.slice(6, 9), digits.slice(9)].filter(Boolean).join(' ');
}

/** Единый порог начала поиска по справочнику — им пользуется и страница справочника (N4). */
export const MIN_QUERY_LENGTH = 3;

/** Имя ГТК — путь по дереву через «:»; пользователю показывается СОБСТВЕННОЕ имя позиции. */
export function leafName(name: string): string {
  const last = (name || '').split(':').pop() ?? '';
  return last.trim() || name;
}
