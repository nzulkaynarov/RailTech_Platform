import type { ThemeConfig } from "antd";

import { RT_ACTION, RT_COMPONENTS, RT_TOKENS } from "./tokens.generated";

/**
 * Тема Платформы: токены общего пакета `packages/ui-tokens` (через `tokens.generated.ts`, копию
 * делает `make -C apps/platform tokens`) плюс компонентные токены макета v3
 * (docs/architecture/platform-frontend.md §3). Строится как тема CRM: `cssVar` даёт переменные `--ant-*`,
 * явные `*Bg/*Border` обязательны — из тёмного сид-цвета antd генерирует серый фон.
 * Значения, которых нет в ui-tokens, заданы здесь по таблице §3; после выхода ui-tokens 0.2.0
 * (INF-P0-2) цвета и шрифт приходят из генерации, а повторы здесь можно удалить.
 */
const reduceMotion =
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Цвета каркаса — из токенов (стандарт интерфейса §2, `packages/ui-tokens/tokens.json`). */
export const PF_COLORS = {
  layoutBg: RT_TOKENS.colorBgLayout,
  containerBg: RT_TOKENS.colorBgContainer,
  tableHeaderBg: RT_COMPONENTS.Table.headerBg,
  split: RT_TOKENS.colorSplit,
  border: RT_TOKENS.colorBorder,
  selectedBg: RT_TOKENS.colorPrimaryBg,
  selectedText: RT_TOKENS.colorPrimaryText,
} as const;

/**
 * Цвет текста тегов по статусу: затравочные `#52c41a`, `#faad14`, `#ff4d4f` на светлом фоне тега
 * не дают 4.5:1, поэтому слово статуса красится этими значениями (docs/architecture/platform-frontend.md §3).
 */
export const TAG_TEXT = {
  success: RT_TOKENS.colorSuccessText,
  warning: RT_TOKENS.colorWarningText,
  error: RT_TOKENS.colorErrorText,
  default: RT_TOKENS.colorTextSecondary,
} as const;

export const appTheme: ThemeConfig = {
  cssVar: true,
  token: {
    ...RT_TOKENS,
    controlHeightSM: 24,
    motion: !reduceMotion,
  },
  components: {
    Menu: {
      itemHeight: 40,
      itemBorderRadius: 6,
      itemSelectedBg: PF_COLORS.selectedBg,
      itemSelectedColor: PF_COLORS.selectedText,
      itemHoverBg: PF_COLORS.layoutBg,
      itemMarginInline: 0,
    },
    Table: {
      headerBg: PF_COLORS.tableHeaderBg,
      headerSplitColor: "transparent",
      rowHoverBg: PF_COLORS.tableHeaderBg,
      rowSelectedBg: PF_COLORS.selectedBg,
      cellPaddingBlock: 12,
      cellPaddingInline: 16,
    },
    // Стандарт интерфейса §2: главная кнопка — графитовая, одна на экран; ссылки, выбор и фокус — акцентным синим.
    Button: {
      colorPrimary: RT_ACTION.default,
      colorPrimaryHover: RT_ACTION.hover,
      colorPrimaryActive: RT_ACTION.active,
      primaryShadow: "none",
      defaultShadow: "none",
      dangerShadow: "none",
    },
    // Подложка переключателя заметна на холсте: вторичная поверхность, активный пункт — белый.
    Segmented: { trackBg: PF_COLORS.tableHeaderBg },
    Card: {
      boxShadowTertiary: "none",
      colorBorderSecondary: RT_TOKENS.colorBorderSecondary,
      borderRadiusLG: 8,
      headerFontSize: 16,
    },
    Tabs: {
      horizontalItemGutter: 20,
      inkBarColor: RT_TOKENS.colorPrimary,
      itemSelectedColor: PF_COLORS.selectedText,
    },
    Tag: { borderRadiusSM: 4, fontSizeSM: 12 },
    Badge: { indicatorHeight: 20, textFontSize: 12 },
    Layout: {
      bodyBg: PF_COLORS.layoutBg,
      headerBg: PF_COLORS.containerBg,
      headerHeight: 56,
      headerPadding: "0 24px",
      siderBg: PF_COLORS.containerBg,
    },
  },
};
