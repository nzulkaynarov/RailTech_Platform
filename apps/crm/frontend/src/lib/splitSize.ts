/**
 * Ширина первой панели antd `Splitter`, запомненная в браузере (Refine/antd P2, п. 7).
 * Хранится доля в процентах: при другой ширине окна раскладка остаётся той же по пропорции.
 * Хранилище недоступно или значение испорчено — панель открывается с размером по умолчанию.
 */
export type SplitBounds = { fallback: number; min: number; max: number };

const PREFIX = "rt.split.";

/** Доля первой панели из размеров в пикселях (`onResizeEnd`); `null`, если размеры неполные. */
export function firstPanePercent(sizes: readonly number[]): number | null {
  const [first, ...rest] = sizes;
  if (first === undefined || !rest.length) return null;
  const total = first + rest.reduce((sum, size) => sum + size, 0);
  if (!(total > 0) || !(first >= 0)) return null;
  return Math.round((first / total) * 1000) / 10;
}

/** Сохранённая доля, ограниченная `min..max`; без сохранения — `fallback`. Результат — `"NN%"`. */
export function readSplit(key: string, bounds: SplitBounds): string {
  let stored: number | null;
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    stored = raw === null ? null : Number(raw);
  } catch {
    stored = null;
  }
  const value = stored !== null && Number.isFinite(stored) ? stored : bounds.fallback;
  return `${String(Math.min(bounds.max, Math.max(bounds.min, value)))}%`;
}

/** Запомнить долю первой панели после перетаскивания разделителя. */
export function saveSplit(key: string, sizes: readonly number[]): void {
  const percent = firstPanePercent(sizes);
  if (percent === null) return;
  try {
    window.localStorage.setItem(PREFIX + key, String(percent));
  } catch {
    // Хранилище недоступно (приватный режим) — при следующем открытии будет размер по умолчанию.
  }
}
