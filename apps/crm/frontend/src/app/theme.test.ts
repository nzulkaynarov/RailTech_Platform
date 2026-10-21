import { theme } from "antd";
import { describe, expect, it } from "vitest";

import { TAG_TEXT, appTheme } from "./theme";
import { RT_COMPONENTS, RT_STATUS_FILL, RT_TOKENS } from "./tokens.generated";

/** WCAG 2.1: относительная яркость и контраст; полупрозрачный цвет смешивается с фоном. */
type Rgb = [number, number, number];

function parse(color: string): { rgb: Rgb; alpha: number } {
  const hex = /^#([0-9a-f]{6})$/i.exec(color);
  if (hex?.[1]) {
    const n = parseInt(hex[1], 16);
    return { rgb: [(n >> 16) & 255, (n >> 8) & 255, n & 255], alpha: 1 };
  }
  const rgba = /^rgba?\(([^)]+)\)$/.exec(color.replace(/\s/g, ""));
  if (!rgba?.[1]) throw new Error(`unsupported color ${color}`);
  const [r = 0, g = 0, b = 0, a = 1] = rgba[1].split(",").map(Number);
  return { rgb: [r, g, b], alpha: a };
}

function blend(fg: string, bg: string): Rgb {
  const top = parse(fg);
  const base = parse(bg).rgb;
  return top.rgb.map((c, i) => c * top.alpha + (base[i] ?? 0) * (1 - top.alpha)) as Rgb;
}

function luminance(rgb: Rgb): number {
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as Rgb;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(fg: string, bg: string): number {
  const a = luminance(blend(fg, bg));
  const b = luminance(parse(bg).rgb);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/** Полупрозрачная заливка поверх белого — как её видит пользователь. */
function opaque(color: string): string {
  const [r, g, b] = blend(color, "#ffffff").map((v) => Math.round(v));
  return `rgb(${String(r)},${String(g)},${String(b)})`;
}

const tk = theme.getDesignToken(appTheme);
const white = "#ffffff";

// [название, текст, фон] — пары, которые реально встречаются в интерфейсе (отчёт 4, таблица контраста).
const pairs: [string, string, string][] = [
  ["primary on container", tk.colorPrimary, tk.colorBgContainer],
  ["primary on layout", tk.colorPrimary, tk.colorBgLayout],
  ["primary on primaryBg (menu)", tk.colorPrimary, tk.colorPrimaryBg],
  ["white on primary button", white, tk.colorPrimary],
  [
    "white on primary hover (#0958d9, решение архитектора вместо #1677ff)",
    white,
    tk.colorPrimaryHover,
  ],
  [
    "primary hover text on container (outlined/link button hover)",
    tk.colorPrimaryHover,
    tk.colorBgContainer,
  ],
  ["primary hover text on layout", tk.colorPrimaryHover, tk.colorBgLayout],
  ["white on primary active", white, tk.colorPrimaryActive],
  ["primaryText on primaryBg (active menu item)", tk.colorPrimaryText, tk.colorPrimaryBg],
  ["primaryText on container", tk.colorPrimaryText, tk.colorBgContainer],
  ["link", tk.colorLink, tk.colorBgContainer],
  ["link hover", tk.colorLinkHover, tk.colorBgContainer],
  ["link active", tk.colorLinkActive, tk.colorBgContainer],
  ["text on layout", tk.colorText, tk.colorBgLayout],
  ["secondary on container", tk.colorTextSecondary, tk.colorBgContainer],
  ["secondary on layout", tk.colorTextSecondary, tk.colorBgLayout],
  ["tertiary on container", tk.colorTextTertiary, tk.colorBgContainer],
  // #767676 (SPEC-v3 §5.2) проходит только на белом; на фоне окна и тонированных заливках подписи AntD
  // (Typography secondary, Empty, Form extra) выводятся цветом colorTextDescription = secondary (#595959).
  ["secondary on primaryBg (bot bubble)", tk.colorTextSecondary, tk.colorPrimaryBg],
  ["description on primaryBg (bot bubble)", tk.colorTextDescription, tk.colorPrimaryBg],
  ["description on successBg (manager bubble)", tk.colorTextDescription, tk.colorSuccessBg],
  ["description on warningBg (system bubble)", tk.colorTextDescription, tk.colorWarningBg],
  ["description on container", tk.colorTextDescription, tk.colorBgContainer],
  ["description on layout", tk.colorTextDescription, tk.colorBgLayout],
  ["placeholder", tk.colorTextPlaceholder, tk.colorBgContainer],
  // Затравочные colorError/Success/Warning (#ff4d4f, #52c41a, #faad14) в текст не попадают — только *Text.
  ["error text", tk.colorErrorText, tk.colorBgContainer],
  ["error hover text", tk.colorErrorHover, tk.colorBgContainer],
  ["white on danger hover", white, tk.colorErrorHover],
  ["white on danger active", white, tk.colorErrorActive],
  ["error on errorBg", tk.colorErrorText, tk.colorErrorBg],
  // Реальные пары компонентов antd: Tag status, Form explain, Button danger, Badge count, Menu/Dropdown danger, Progress.
  ["Tag error: colorError on colorErrorBg", tk.colorError, tk.colorErrorBg],
  ["Tag warning: colorWarning on colorWarningBg", tk.colorWarning, tk.colorWarningBg],
  ["Tag success: colorSuccess on colorSuccessBg", tk.colorSuccess, tk.colorSuccessBg],
  ["Form explain error: colorError on container", tk.colorError, tk.colorBgContainer],
  ["Form explain warning: colorWarning on container", tk.colorWarning, tk.colorBgContainer],
  ["Typography danger: colorErrorText on container", tk.colorErrorText, tk.colorBgContainer],
  ["Button danger primary: white on colorError", white, tk.colorError],
  ["Button danger outlined/text/link: colorError on container", tk.colorError, tk.colorBgContainer],
  ["Button danger text hover: colorErrorHover on errorBg", tk.colorErrorHover, tk.colorErrorBg],
  ["colorErrorTextHover on container", tk.colorErrorTextHover, tk.colorBgContainer],
  ["colorErrorTextActive on container", tk.colorErrorTextActive, tk.colorBgContainer],
  ["Badge count: white on colorError", white, tk.colorError],
  ["Menu/Dropdown danger: colorError on container", tk.colorError, tk.colorBgContainer],
  ["Menu danger selected: white on colorError", white, tk.colorError],
  ["Progress success: colorSuccess on container", tk.colorSuccess, tk.colorBgContainer],
  ["colorSuccessHover on container", tk.colorSuccessHover, tk.colorBgContainer],
  ["colorWarningHover on container", tk.colorWarningHover, tk.colorBgContainer],
  ["link hover on container", tk.colorLinkHover, tk.colorBgContainer],
  ["link active on container", tk.colorLinkActive, tk.colorBgContainer],
  ["success on successBg", tk.colorSuccessText, tk.colorSuccessBg],
  ["success on container", tk.colorSuccessText, tk.colorBgContainer],
  ["warning on warningBg", tk.colorWarningText, tk.colorWarningBg],
  ["warning on container", tk.colorWarningText, tk.colorBgContainer],
  ["info on infoBg", tk.colorInfoText, tk.colorInfoBg],
  // Текст preset-тега — `<цвет>7` (antd genPresetColor), фон — `<цвет>1`; green/cyan/orange — из TAG_TEXT.
  ["tag gold", TAG_TEXT["gold"] ?? "", tk.gold1],
  ["tag purple (RT_TAG_TEXT)", TAG_TEXT["purple"] ?? "", tk.purple1],
  ["tag green", TAG_TEXT["green"] ?? "", tk.green1],
  ["tag cyan", TAG_TEXT["cyan"] ?? "", tk.cyan1],
  ["tag orange", TAG_TEXT["orange"] ?? "", tk.orange1],
  ["tag red", tk.red7, tk.red1],
  ["tag blue", tk.blue7, tk.blue1],
  ["tag geekblue", tk.geekblue7, tk.geekblue1],
  ["tag purple", tk.purple7, tk.purple1],
  ["default tag", tk.colorText, opaque(tk.colorFillQuaternary)],
];

// Пары ниже 4.5:1, зафиксированные SPEC-v3 §5.2 (docs/QUESTIONS.md, Q-INF-P0-2-3). Тест держит их в 3:1..4.5:1 и
// требует перенести пару в основной список, когда она начнёт проходить.
const knownBelowAa: [string, string, string][] = [
  ["tertiary on layout (Q-INF-P0-2-3)", tk.colorTextTertiary, tk.colorBgLayout],
  ["tertiary on primaryBg (Q-INF-P0-2-3)", tk.colorTextTertiary, tk.colorPrimaryBg],
];

describe("theme contrast (WCAG 2.1 AA, 1.4.3)", () => {
  it("computes the reference ratios", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contrast("#1677ff", "#ffffff")).toBeCloseTo(4.1, 1);
    expect(contrast("rgba(0,0,0,0.45)", "#ffffff")).toBeCloseTo(3.36, 1);
  });

  it.each(pairs)("%s ≥ 4.5:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(knownBelowAa)("known exception: %s stays within 3:1..4.5:1", (_name, fg, bg) => {
    const ratio = contrast(fg, bg);
    expect(ratio).toBeGreaterThanOrEqual(3);
    expect(ratio).toBeLessThan(4.5);
  });

  it("keeps seed status colours out of antd tokens (text and white-on-fill pairs)", () => {
    expect(tk.colorErrorText).toBe("#a8071a");
    expect(tk.colorSuccessText).toBe("#237804");
    expect(tk.colorWarningText).toBe("#874d00");
    expect(RT_TOKENS.colorError).toBe("#a8071a");
    expect(RT_TOKENS.colorWarning).toBe("#874d00");
    expect(RT_TOKENS.colorSuccess).toBe("#237804");
    expect(RT_STATUS_FILL).toEqual({ error: "#ff4d4f", warning: "#faad14", success: "#52c41a" });
  });

  it("ships component tokens for the Platform theme", () => {
    expect(RT_COMPONENTS.Table.cellPaddingBlock).toBe(12);
    expect(RT_COMPONENTS.Menu.itemSelectedColor).toBe(RT_TOKENS.colorPrimaryText);
  });

  it("exposes css variables for custom stylesheets", () => {
    expect(appTheme.cssVar).toBe(true);
  });

  it("reads colours from the shared ui-tokens package", () => {
    expect(appTheme.token?.colorPrimary).toBe(RT_TOKENS.colorPrimary);
    expect(appTheme.token?.colorError).toBe(RT_TOKENS.colorError);
    expect(tk.colorPrimary).toBe(RT_TOKENS.colorPrimary);
  });
});
