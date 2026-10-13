import type { ThemeConfig } from "antd";

/**
 * Тема CRM: токены, проходящие WCAG 2.1 AA 4.5:1 (дизайн-аудит 2026-10-11, отчёт 4,
 * таблица контраста). `cssVar` даёт переменные `--ant-*` для собственных CSS-файлов.
 * Явные `*Bg/*Border` обязательны: из тёмного сид-цвета antd генерирует серый фон,
 * и контраст падает. Палитры (`green7`, `cyan7`…) в режиме `cssVar` antd 5 не переопределяет —
 * текст preset-тегов задаётся через `TAG_TEXT` (CSS-переменные `--crm-tag-*`, см. `applyTagColors`).
 */
const reduceMotion =
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const appTheme: ThemeConfig = {
  cssVar: true,
  token: {
    colorPrimary: "#0958d9",
    colorPrimaryHover: "#003eb3",
    colorPrimaryActive: "#002c8c",
    colorPrimaryBg: "#e6f4ff",
    colorInfo: "#0958d9",
    colorInfoBg: "#e6f4ff",
    colorInfoBorder: "#91caff",
    colorLink: "#0958d9",
    colorLinkHover: "#003eb3",
    colorLinkActive: "#002c8c",
    colorTextTertiary: "rgba(0,0,0,0.6)",
    colorTextDescription: "rgba(0,0,0,0.6)",
    colorTextPlaceholder: "rgba(0,0,0,0.55)",
    colorError: "#cf1322",
    colorErrorHover: "#a8071a",
    colorErrorActive: "#820014",
    colorErrorBg: "#fff2f0",
    colorErrorBorder: "#ffccc7",
    colorSuccess: "#237804",
    colorSuccessBg: "#f6ffed",
    colorSuccessBorder: "#b7eb8f",
    colorWarning: "#874d00",
    colorWarningBg: "#fffbe6",
    colorWarningBorder: "#ffe58f",
    motion: !reduceMotion,
  },
  components: {
    /**
     * Плотность таблиц — один раз здесь, а не `size="small"` на каждой странице: отступы ячеек
     * обычной таблицы = отступам `small` (paddingXS, 8 px). Кнопки и поля остаются обычного
     * размера — зоны касания на телефоне не уменьшаются (глобальный `componentSize` не берём).
     */
    Table: { cellPaddingBlock: 8, cellPaddingInline: 8 },
  },
};

/**
 * Текст preset-тегов `Tag color="green|cyan|orange"` (antd: `<цвет>7`) — по умолчанию 3.4:1 на
 * фоне `<цвет>1`. Значения с контрастом ≥ 4.5:1; остальные preset-цвета проходят и так.
 */
export const TAG_TEXT: Record<string, string> = {
  green: "#237804",
  cyan: "#006d75",
  orange: "#874d00",
};

/** Выставляет `--crm-tag-<цвет>` на `<html>`; читает их `styles/a11y.css`. */
export function applyTagColors(root: HTMLElement = document.documentElement): void {
  for (const [color, value] of Object.entries(TAG_TEXT)) {
    root.style.setProperty(`--crm-tag-${color}`, value);
  }
}
