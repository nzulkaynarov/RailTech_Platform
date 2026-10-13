import { theme } from "antd";
import { describe, expect, it } from "vitest";

import { TAG_TEXT, appTheme } from "./theme";
import { RT_TOKENS } from "./tokens.generated";

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
  ["white on primary hover", white, tk.colorPrimaryHover],
  ["primary hover text", tk.colorPrimaryHover, tk.colorBgContainer],
  ["link", tk.colorLink, tk.colorBgContainer],
  ["link hover", tk.colorLinkHover, tk.colorBgContainer],
  ["link active", tk.colorLinkActive, tk.colorBgContainer],
  ["text on layout", tk.colorText, tk.colorBgLayout],
  ["secondary on container", tk.colorTextSecondary, tk.colorBgContainer],
  ["secondary on layout", tk.colorTextSecondary, tk.colorBgLayout],
  ["tertiary on container", tk.colorTextTertiary, tk.colorBgContainer],
  ["tertiary on layout", tk.colorTextTertiary, tk.colorBgLayout],
  ["tertiary on primaryBg (bot bubble)", tk.colorTextTertiary, tk.colorPrimaryBg],
  ["tertiary on successBg (manager bubble)", tk.colorTextTertiary, tk.colorSuccessBg],
  ["tertiary on warningBg (system bubble)", tk.colorTextTertiary, tk.colorWarningBg],
  ["description on container", tk.colorTextDescription, tk.colorBgContainer],
  ["description on layout", tk.colorTextDescription, tk.colorBgLayout],
  ["placeholder", tk.colorTextPlaceholder, tk.colorBgContainer],
  ["error text", tk.colorError, tk.colorBgContainer],
  ["white on danger button", white, tk.colorError],
  ["white on danger hover", white, tk.colorErrorHover],
  ["error on errorBg", tk.colorErrorText, tk.colorErrorBg],
  ["success on successBg", tk.colorSuccessText, tk.colorSuccessBg],
  ["success on container", tk.colorSuccess, tk.colorBgContainer],
  ["warning on warningBg", tk.colorWarningText, tk.colorWarningBg],
  ["warning on container", tk.colorWarning, tk.colorBgContainer],
  ["info on infoBg", tk.colorInfoText, tk.colorInfoBg],
  // Текст preset-тега — `<цвет>7` (antd genPresetColor), фон — `<цвет>1`; green/cyan/orange — из TAG_TEXT.
  ["tag green", TAG_TEXT["green"] ?? "", tk.green1],
  ["tag cyan", TAG_TEXT["cyan"] ?? "", tk.cyan1],
  ["tag orange", TAG_TEXT["orange"] ?? "", tk.orange1],
  ["tag red", tk.red7, tk.red1],
  ["tag blue", tk.blue7, tk.blue1],
  ["tag geekblue", tk.geekblue7, tk.geekblue1],
  ["tag purple", tk.purple7, tk.purple1],
  ["default tag", tk.colorText, opaque(tk.colorFillQuaternary)],
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

  it("exposes css variables for custom stylesheets", () => {
    expect(appTheme.cssVar).toBe(true);
  });

  it("reads colours from the shared ui-tokens package", () => {
    expect(appTheme.token?.colorPrimary).toBe(RT_TOKENS.colorPrimary);
    expect(appTheme.token?.colorError).toBe(RT_TOKENS.colorError);
    expect(tk.colorPrimary).toBe(RT_TOKENS.colorPrimary);
  });
});
