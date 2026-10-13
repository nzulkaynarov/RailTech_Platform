import type { ThemeConfig } from "antd";

import { RT_TABLE_CELL_PADDING, RT_TAG_TEXT, RT_TOKENS } from "./tokens.generated";

/**
 * Тема CRM: токены из общего пакета ансамбля `packages/ui-tokens` (M0-INF-05) — цвета, шрифт,
 * радиусы, плотность одни на CRM, ERP и Cabinet. Значения проходят WCAG 2.1 AA 4.5:1
 * (дизайн-аудит 2026-10-11, отчёт 4, таблица контраста); проверка — `theme.test.ts`.
 * `tokens.generated.ts` не править руками: `make tokens` из корня перегенерирует его из `tokens.json`.
 * `cssVar` даёт переменные `--ant-*` для собственных CSS-файлов. Явные `*Bg/*Border` обязательны:
 * из тёмного сид-цвета antd генерирует серый фон, и контраст падает. Палитры (`green7`, `cyan7`…)
 * в режиме `cssVar` antd 5 не переопределяет — текст preset-тегов задаётся через `TAG_TEXT`
 * (CSS-переменные `--crm-tag-*`, см. `applyTagColors`).
 */
const reduceMotion =
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const appTheme: ThemeConfig = {
  cssVar: true,
  token: {
    ...RT_TOKENS,
    motion: !reduceMotion,
  },
  components: {
    /**
     * Плотность таблиц — один раз здесь, а не `size="small"` на каждой странице: отступы ячеек
     * обычной таблицы = отступам `small` (paddingXS, 8 px). Кнопки и поля остаются обычного
     * размера — зоны касания на телефоне не уменьшаются (глобальный `componentSize` не берём).
     */
    Table: { cellPaddingBlock: RT_TABLE_CELL_PADDING, cellPaddingInline: RT_TABLE_CELL_PADDING },
  },
};

/**
 * Текст preset-тегов `Tag color="green|cyan|orange"` (antd: `<цвет>7`) — по умолчанию 3.4:1 на
 * фоне `<цвет>1`. Значения с контрастом ≥ 4.5:1 из общих токенов; остальные preset-цвета проходят и так.
 */
export const TAG_TEXT: Record<string, string> = RT_TAG_TEXT;

/** Выставляет `--crm-tag-<цвет>` на `<html>`; читает их `styles/a11y.css`. */
export function applyTagColors(root: HTMLElement = document.documentElement): void {
  for (const [color, value] of Object.entries(TAG_TEXT)) {
    root.style.setProperty(`--crm-tag-${color}`, value);
  }
}
