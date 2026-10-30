// Сгенерировано из packages/ui-tokens/tokens.json (v0.2.0) — не править руками, запускать make tokens.
// Общие токены ансамбля для темы AntD (CRM, Платформа). Контраст WCAG 2.1 AA проверяют theme.test.ts (CRM) и contrast.test.mjs (пакет).
export const RT_TOKENS = {
  colorPrimary: "#1668dc",
  colorPrimaryHover: "#0958d9",
  colorPrimaryActive: "#003eb3",
  colorPrimaryBg: "#e6f4ff",
  colorPrimaryBorder: "#91caff",
  colorPrimaryText: "#0958d9",
  colorInfo: "#0958d9",
  colorInfoBg: "#e6f4ff",
  colorInfoBorder: "#91caff",
  colorInfoText: "#0958d9",
  colorLink: "#1668dc",
  colorLinkHover: "#0958d9",
  colorLinkActive: "#003eb3",
  colorText: "#1f1f1f",
  colorTextSecondary: "#595959",
  colorTextTertiary: "#6e6e6e",
  colorTextDescription: "#595959",
  colorTextPlaceholder: "#6e6e6e",
  colorError: "#a8071a",
  colorErrorHover: "#cf1322",
  colorErrorActive: "#820014",
  colorErrorBg: "#fff2f0",
  colorErrorBorder: "#ffccc7",
  colorErrorText: "#a8071a",
  colorErrorTextHover: "#cf1322",
  colorErrorTextActive: "#820014",
  colorSuccess: "#237804",
  colorSuccessHover: "#135200",
  colorSuccessActive: "#092b00",
  colorSuccessBg: "#f6ffed",
  colorSuccessBorder: "#b7eb8f",
  colorSuccessText: "#237804",
  colorWarning: "#874d00",
  colorWarningHover: "#613400",
  colorWarningActive: "#3d2100",
  colorWarningBg: "#fffbe6",
  colorWarningBorder: "#ffe58f",
  colorWarningText: "#874d00",
  colorBorder: "#d9d9d9",
  colorSplit: "#f0f0f0",
  colorBorderSecondary: "#f0f0f0",
  colorBgLayout: "#f5f5f5",
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
  blue: "#0958d9",
  green: "#237804",
  cyan: "#006d75",
  orange: "#874d00",
  gold: "#874d00",
  red: "#a8071a",
  purple: "#531dab",
};

/** Затравочные цвета статусов (SPEC-v3 §5.2) — для графиков и заливок БЕЗ текста; в текст и под белый текст не идут. */
export const RT_STATUS_FILL = {
  error: "#ff4d4f",
  warning: "#faad14",
  success: "#52c41a",
};

/** Плотность таблиц CRM: отступы ячеек обычной таблицы = small (paddingXS). У Платформы — RT_COMPONENTS.Table. */
export const RT_TABLE_CELL_PADDING = 8;

/** Компонентные токены Платформы (ConfigProvider theme.components; docs/architecture/platform-frontend.md §3). CRM их не подключает. */
export const RT_COMPONENTS = {
  Menu: {
    itemHeight: 40,
    itemBorderRadius: 6,
    itemSelectedBg: "#e6f4ff",
    itemSelectedColor: "#0958d9",
    itemHoverBg: "#f5f5f5",
    itemMarginInline: 0,
  },
  Table: {
    headerBg: "#fafafa",
    headerSplitColor: "transparent",
    rowHoverBg: "#fafafa",
    rowSelectedBg: "#e6f4ff",
    cellPaddingBlock: 12,
    cellPaddingInline: 16,
  },
  Card: {
    headerFontSize: 16,
  },
  Tabs: {
    horizontalItemGutter: 20,
    inkBarColor: "#1668dc",
    itemSelectedColor: "#0958d9",
  },
  Badge: {
    indicatorHeight: 20,
    textFontSize: 12,
  },
  Layout: {
    bodyBg: "#f5f5f5",
    headerBg: "#ffffff",
    headerHeight: 56,
    headerPadding: "0 24px",
    siderBg: "#ffffff",
  },
} as const;
