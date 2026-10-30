/** Ширина, ниже которой таблица списка прокручивается в своей области: сумма ширин колонок, гибкая — `flexible` (UX-1c, S9). */
export function tableMinWidth(widths: readonly (number | null)[], flexible = 200): number {
  return widths.reduce<number>((sum, width) => sum + (width ?? flexible), 0);
}
