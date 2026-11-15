// Сгенерировано из packages/ui-tokens/tokens.json (v0.3.0) — не править руками, запускать make tokens.
// Общие токены ансамбля для темы AntD (CRM, Платформа). Контраст WCAG 2.1 AA проверяют theme.test.ts (CRM) и contrast.test.mjs (пакет).
export const RT_TOKENS = {
  colorPrimary: "#1d4ed8",
  colorPrimaryHover: "#1e40af",
  colorPrimaryActive: "#1e3a8a",
  colorPrimaryBg: "#eff6ff",
  colorPrimaryBorder: "#bfdbfe",
  colorPrimaryText: "#1d4ed8",
  colorInfo: "#1d4ed8",
  colorInfoBg: "#eff6ff",
  colorInfoBorder: "#bfdbfe",
  colorInfoText: "#1d4ed8",
  colorLink: "#1d4ed8",
  colorLinkHover: "#1e40af",
  colorLinkActive: "#1e3a8a",
  colorText: "#0f172a",
  colorTextSecondary: "#475569",
  colorTextTertiary: "#5f6f86",
  colorTextDescription: "#475569",
  colorTextPlaceholder: "#5f6f86",
  colorError: "#be123c",
  colorErrorHover: "#9f1239",
  colorErrorActive: "#881337",
  colorErrorBg: "#fef2f2",
  colorErrorBorder: "#fecdd3",
  colorErrorText: "#be123c",
  colorErrorTextHover: "#9f1239",
  colorErrorTextActive: "#881337",
  colorSuccess: "#15803d",
  colorSuccessHover: "#166534",
  colorSuccessActive: "#14532d",
  colorSuccessBg: "#f0fdf4",
  colorSuccessBorder: "#bbf7d0",
  colorSuccessText: "#15803d",
  colorWarning: "#b45309",
  colorWarningHover: "#92400e",
  colorWarningActive: "#78350f",
  colorWarningBg: "#fffbeb",
  colorWarningBorder: "#fde68a",
  colorWarningText: "#b45309",
  colorBorder: "#cbd5e1",
  colorSplit: "#f1f5f9",
  colorBorderSecondary: "#e2e8f0",
  colorBgLayout: "#f8fafc",
  colorBgContainer: "#ffffff",
  fontFamily: "'Inter Variable', Inter, -apple-system, \"Segoe UI\", Roboto, Arial, sans-serif",
  fontFamilyCode: "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace",
  fontSize: 14,
  borderRadius: 6,
  borderRadiusSM: 4,
  borderRadiusLG: 8,
  controlHeight: 32,
  controlHeightSM: 24,
} as const;

/** Текст preset-тегов Tag color="blue|green|cyan|orange|gold|red|purple" с контрастом ≥ 4.5:1 на фоне тега. */
export const RT_TAG_TEXT: Record<string, string> = {
  blue: "#1d4ed8",
  green: "#15803d",
  cyan: "#0e7490",
  orange: "#b45309",
  gold: "#b45309",
  red: "#be123c",
  purple: "#6d28d9",
};

/** Затравочные цвета статусов (SPEC-v3 §5.2) — для графиков и заливок БЕЗ текста; в текст и под белый текст не идут. */
export const RT_STATUS_FILL = {
  error: "#e11d48",
  warning: "#d97706",
  success: "#16a34a",
};

/** Плотность таблиц CRM: отступы ячеек обычной таблицы = small (paddingXS). У Платформы — RT_COMPONENTS.Table. */
export const RT_TABLE_CELL_PADDING = 8;

/** Компонентные токены Платформы (ConfigProvider theme.components; docs/architecture/platform-frontend.md §3). */
export const RT_COMPONENTS = {
  Menu: {
    itemHeight: 40,
    itemBorderRadius: 6,
    itemSelectedBg: "#eff6ff",
    itemSelectedColor: "#1d4ed8",
    itemHoverBg: "#f8fafc",
    itemMarginInline: 0,
  },
  Table: {
    headerBg: "#f1f5f9",
    headerSplitColor: "transparent",
    rowHoverBg: "#f8fafc",
    rowSelectedBg: "#eff6ff",
    cellPaddingBlock: 12,
    cellPaddingInline: 16,
  },
  Card: {
    headerFontSize: 16,
  },
  Tabs: {
    horizontalItemGutter: 20,
    inkBarColor: "#1d4ed8",
    itemSelectedColor: "#1d4ed8",
  },
  Badge: {
    indicatorHeight: 20,
    textFontSize: 12,
  },
  Layout: {
    bodyBg: "#f8fafc",
    headerBg: "#ffffff",
    headerHeight: 56,
    headerPadding: "0 24px",
    siderBg: "#ffffff",
  },
} as const;
