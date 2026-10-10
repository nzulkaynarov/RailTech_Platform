import type { ThemeConfig } from "antd";

/**
 * Тема CRM: токены, проходящие WCAG 2.1 AA 4.5:1 (дизайн-аудит 2026-10-11, отчёт 4,
 * таблица контраста). `cssVar` даёт переменные `--ant-*` для собственных CSS-файлов.
 * Явные `*Bg/*Border` обязательны: из тёмного сид-цвета antd генерирует серый фон,
 * и контраст падает (green7/cyan7/orange7 — текст preset-тегов `Tag color="green"` и т. п.).
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
    green7: "#237804",
    cyan7: "#006d75",
    orange7: "#ad4e00",
    motion: !reduceMotion,
  },
};
