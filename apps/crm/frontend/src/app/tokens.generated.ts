// Сгенерировано из packages/ui-tokens/tokens.json (v0.1.0) — не править руками, запускать make tokens.
// Общие токены ансамбля для темы AntD (CRM). Контраст WCAG 2.1 AA проверяет theme.test.ts.
export const RT_TOKENS = {
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
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji'",
  fontFamilyCode: "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace",
  fontSize: 14,
  borderRadius: 6,
  borderRadiusSM: 4,
  borderRadiusLG: 8,
  controlHeight: 32,
} as const;

/** Текст preset-тегов Tag color="green|cyan|orange" с контрастом ≥ 4.5:1 на фоне тега. */
export const RT_TAG_TEXT: Record<string, string> = {
  green: "#237804",
  cyan: "#006d75",
  orange: "#874d00",
};

/** Плотность таблиц: отступы ячеек обычной таблицы = small (paddingXS). */
export const RT_TABLE_CELL_PADDING = 8;
