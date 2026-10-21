import { describe, expect, it } from "vitest";

import { PF_COLORS, TAG_TEXT, appTheme } from "./theme";
import { RT_TOKENS } from "./tokens.generated";

/** WCAG 2.1: относительная яркость и контраст двух непрозрачных hex-цветов. */
function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const [r = 0, g = 0, b = 0] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(fg: string, bg: string): number {
  const [a, b] = [luminance(fg), luminance(bg)];
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

describe("appTheme", () => {
  it("uses CSS variables and ui-tokens values", () => {
    expect(appTheme.cssVar).toBe(true);
    expect(appTheme.token?.colorPrimary).toBe(RT_TOKENS.colorPrimary);
  });

  it("carries the component tokens of the v3 mock-up", () => {
    expect(appTheme.components?.Layout?.headerHeight).toBe(56);
    expect(appTheme.components?.Menu?.itemHeight).toBe(40);
    expect(appTheme.components?.Table?.cellPaddingBlock).toBe(12);
    expect(appTheme.components?.Card?.boxShadowTertiary).toBe("none");
  });

  it.each([
    ["primary on white", RT_TOKENS.colorPrimary, "#ffffff"],
    ["selected menu text", PF_COLORS.selectedText, PF_COLORS.selectedBg],
    ["success tag text", TAG_TEXT.success, "#f6ffed"],
    ["warning tag text", TAG_TEXT.warning, "#fffbe6"],
    ["error tag text", TAG_TEXT.error, "#fff2f0"],
    ["neutral tag text", TAG_TEXT.default, PF_COLORS.split],
  ])("%s keeps WCAG AA 4.5:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });
});
