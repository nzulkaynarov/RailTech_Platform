import type { ThemeConfig } from "antd";

import { RT_TOKENS } from "./tokens.generated";

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

/** Цвета макета v3 §5.2, одинаковые в ui-tokens 0.1 и 0.2. */
export const PF_COLORS = {
  layoutBg: "#f5f5f5",
  containerBg: "#ffffff",
  tableHeaderBg: "#fafafa",
  split: "#f0f0f0",
  border: "#d9d9d9",
  selectedBg: "#e6f4ff",
  selectedText: "#0958d9",
} as const;

/**
 * Цвет текста тегов по статусу: затравочные `#52c41a`, `#faad14`, `#ff4d4f` на светлом фоне тега
 * не дают 4.5:1, поэтому слово статуса красится этими значениями (docs/architecture/platform-frontend.md §3).
 */
export const TAG_TEXT = {
  success: "#237804",
  warning: "#874d00",
  error: "#a8071a",
  default: "#595959",
} as const;

export const appTheme: ThemeConfig = {
  cssVar: true,
  token: {
    ...RT_TOKENS,
    colorBgLayout: PF_COLORS.layoutBg,
    colorBgContainer: PF_COLORS.containerBg,
    colorBorder: PF_COLORS.border,
    colorSplit: PF_COLORS.split,
    colorBorderSecondary: PF_COLORS.split,
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
    Card: {
      boxShadowTertiary: "none",
      colorBorderSecondary: PF_COLORS.split,
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
