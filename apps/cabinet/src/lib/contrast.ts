/**
 * Контраст WCAG 2.1 (1.4.3 текст ≥ 4.5:1, 1.4.11 значки и кольцо фокуса ≥ 3:1) — те же формулы, что
 * `packages/ui-tokens/contrast.test.mjs`. Нужен в рантайме Mini App: цвет темы Telegram берётся, только если пары с ним
 * проходят AA (`telegram/theme.ts`, CAB-FIX-3).
 */
const HEX6 = /^#([0-9a-f]{6})$/i;
const HEX3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i;

/** `#rgb` / `#rrggbb` → `#rrggbb` в нижнем регистре; иное (`#rrggbbaa`, имена, rgb()) — `null`. */
export function normalizeHex(value: string | undefined | null): string | null {
  const text = value?.trim() ?? '';
  const short = HEX3.exec(text);
  if (short) return `#${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}`.toLowerCase();
  return HEX6.test(text) ? text.toLowerCase() : null;
}

function rgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Цвет `fg` с прозрачностью `alpha` поверх `bg` — как его видит пользователь (`bg-success/10`). */
export function over(fg: string, alpha: number, bg: string): string {
  const f = rgb(fg);
  const b = rgb(bg);
  return `#${f.map((v, i) => Math.round(v * alpha + b[i] * (1 - alpha)).toString(16).padStart(2, '0')).join('')}`;
}

function luminance(hex: string): number {
  const [r, g, b] = rgb(hex).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(fg: string, bg: string): number {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}
