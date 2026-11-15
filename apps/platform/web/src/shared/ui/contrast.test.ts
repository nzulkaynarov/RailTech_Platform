import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "src/shared/ui/ui.css"), "utf8");
// Цвета в CSS — переменные токенов (стандарт интерфейса, UI-1): значение читается из tokens.generated.css.
const tokens = readFileSync(join(process.cwd(), "src/app/tokens.generated.css"), "utf8");
function resolve(text: string): string {
  return text.replace(/var\((--rt-[a-z0-9-]+)\)/g, (whole, name: string) => {
    const found = new RegExp(`${name}:\\s*([^;]+);`).exec(tokens);
    return found?.[1] ?? whole;
  });
}

/**
 * Контраст пар цветов, заданных в `ui.css`: значения берутся из самого файла, так что правка токена, после которой пара
 * перестаёт проходить WCAG 2.1 AA, ломает тест, а не интерфейс (текст ≥ 4.5:1, графика и рамки ≥ 3:1 — 1.4.11).
 */
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

/** Значение свойства из правила с точно таким селектором (`.a .b`); для `border` берётся цвет, для `background` — цвет заливки. */
function value(selector: string, property: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  if (!rule) throw new Error(`нет правила ${selector}`);
  const declaration = new RegExp(`(?:^|;|\\s)${property}:\\s*([^;]+);`).exec(rule[1] ?? "");
  const hex = /#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/.exec(resolve(declaration?.[1] ?? ""));
  if (!hex) throw new Error(`нет цвета ${property} в ${selector}`);
  const [, h = ""] = /#(.*)/.exec(hex[0]) ?? [];
  return h.length === 3 ? `#${h.replace(/./g, "$&$&")}` : hex[0];
}

const WHITE = "#ffffff";
// Поверхности стандарта интерфейса §2: холст, вторичная, фон выбранного и фоны статусов.
const SURFACES = [WHITE, "#f8fafc", "#f1f5f9", "#eff6ff", "#fffbeb", "#f0fdf4", "#fef2f2"];

describe("контраст общих компонентов (ui.css)", () => {
  it.each(SURFACES)("подпись .pf-hint на %s ≥ 4.5:1", (surface) => {
    expect(contrast(value(".pf-hint", "color"), surface)).toBeGreaterThanOrEqual(4.5);
  });

  it("SourceBanner: текст и значок на фоне плашки", () => {
    const background = value(".pf-source", "background");
    expect(contrast(value(".pf-source", "color"), background)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(value(".pf-source-icon", "color"), background)).toBeGreaterThanOrEqual(3);
  });

  it("RequestSteps: номер и подпись в каждом состоянии", () => {
    const num = ".pf-step-num";
    expect(contrast(value(num, "color"), value(num, "background"))).toBeGreaterThanOrEqual(4.5);
    for (const state of ["done", "current"]) {
      const sel = `.pf-step--${state} .pf-step-num`;
      expect(contrast(value(sel, "color"), value(sel, "background")), state).toBeGreaterThanOrEqual(
        4.5,
      );
    }
    expect(contrast(value(".pf-step-label", "color"), WHITE)).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(value(".pf-step--upcoming .pf-step-label", "color"), WHITE),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(value(".pf-step--current .pf-step-label", "color"), WHITE),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("RequestSteps: заливка пройденного шага ≥ 3:1 на белом (1.4.11); номер внутри кружка — текст, он проверен выше", () => {
    expect(
      contrast(value(".pf-step--done .pf-step-num", "background"), WHITE),
    ).toBeGreaterThanOrEqual(3);
  });

  it("History: точка каждого состояния отличима от белого фона ≥ 3:1", () => {
    expect(contrast(value(".pf-history-dot", "border"), WHITE)).toBeGreaterThanOrEqual(3);
    expect(contrast(value(".pf-history-dot--done", "background"), WHITE)).toBeGreaterThanOrEqual(3);
    expect(
      contrast(value(".pf-history-dot--waiting", "border-color"), WHITE),
    ).toBeGreaterThanOrEqual(3);
  });
});
