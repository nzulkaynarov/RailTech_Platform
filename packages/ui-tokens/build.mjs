#!/usr/bin/env node
// Генератор из tokens.json (единственный источник) в потребляемые форматы:
//   dist/tokens.css   — CSS-переменные --rt-* (любой фронтенд)
//   dist/shadcn.css   — переменные shadcn/ui (--primary, --destructive, --radius…) + @theme для Tailwind 4 (ERP, Cabinet)
//   dist/antd.ts      — объект token для ThemeConfig AntD (CRM); копия — apps/crm/frontend/src/app/tokens.generated.ts
// Без зависимостей: node ≥ 20. Запуск: make tokens (корень) или make -C packages/ui-tokens build.
// Вывод TS намеренно в формате prettier (двойные кавычки, запятые в конце), чтобы проходить prettier --check в CRM.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tokens = JSON.parse(readFileSync(join(here, "tokens.json"), "utf8"));
const banner = `/* Сгенерировано из packages/ui-tokens/tokens.json (v${tokens.version}) — не править руками, запускать make tokens. */`;

const px = (n) => `${n}px`;
const rem = (n) => `${n / 16}rem`;
const tsValue = (v) => (typeof v === "number" ? String(v) : JSON.stringify(v));
// Строка длиннее printWidth (100) — prettier переносит значение на новую строку.
const tsEntry = (k, v) => {
  const one = `  ${k}: ${tsValue(v)},`;
  return one.length <= 100 ? one : `  ${k}:\n    ${tsValue(v)},`;
};
const tsObject = (obj) => `{\n${Object.entries(obj).map(([k, v]) => tsEntry(k, v)).join("\n")}\n}`;

// ─── dist/tokens.css ───────────────────────────────────────────────────────────────────────
const vars = [];
for (const [group, shades] of Object.entries(tokens.color)) {
  for (const [name, value] of Object.entries(shades)) vars.push([`--rt-color-${group}-${name}`, value]);
}
vars.push(["--rt-font-family", tokens.font.family], ["--rt-font-family-mono", tokens.font.familyMono]);
for (const [name, value] of Object.entries(tokens.font.size)) vars.push([`--rt-font-size-${name}`, px(value)]);
for (const [name, value] of Object.entries(tokens.font.lineHeight)) vars.push([`--rt-line-height-${name}`, String(value)]);
for (const [name, value] of Object.entries(tokens.radius)) vars.push([`--rt-radius-${name}`, px(value)]);
for (const [name, value] of Object.entries(tokens.density)) {
  const kebab = name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
  vars.push([`--rt-density-${kebab}`, px(value)]);
}
const tokensCss = `${banner}\n:root {\n${vars.map(([k, v]) => `  ${k}: ${v};`).join("\n")}\n}\n`;

// ─── dist/shadcn.css ───────────────────────────────────────────────────────────────────────
const c = tokens.color;
const shadcnVars = {
  "--background": c.surface.background,
  "--foreground": c.text.default,
  "--card": c.surface.card,
  "--card-foreground": c.text.default,
  "--popover": c.surface.card,
  "--popover-foreground": c.text.default,
  "--primary": c.primary.default,
  "--primary-foreground": c.primary.foreground,
  "--secondary": c.surface.muted,
  "--secondary-foreground": c.text.default,
  "--muted": c.surface.muted,
  "--muted-foreground": c.text.tertiary,
  "--accent": c.primary.bg,
  "--accent-foreground": c.primary.active,
  "--destructive": c.error.default,
  "--destructive-foreground": c.error.foreground,
  "--success": c.success.default,
  "--success-foreground": c.success.foreground,
  "--warning": c.warning.default,
  "--warning-foreground": c.warning.foreground,
  "--info": c.info.default,
  "--info-foreground": c.info.foreground,
  "--border": c.surface.border,
  "--input": c.surface.border,
  "--ring": c.surface.ring,
  "--radius": rem(tokens.radius.md),
  "--font-sans": tokens.font.family,
  "--font-mono": tokens.font.familyMono,
};
const shadcnCss = `${banner}
/* Подключение (ERP, Cabinet): @import "tailwindcss"; @import "../../../packages/ui-tokens/dist/shadcn.css";
   Тёмная тема (.dark) задаётся приложением поверх; здесь — токены светлой темы. */
:root {
${Object.entries(shadcnVars)
  .map(([k, v]) => `  ${k}: ${v};`)
  .join("\n")}
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-success: var(--success);
  --color-success-foreground: var(--success-foreground);
  --color-warning: var(--warning);
  --color-warning-foreground: var(--warning-foreground);
  --color-info: var(--info);
  --color-info-foreground: var(--info-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --radius-sm: ${rem(tokens.radius.sm)};
  --radius-md: ${rem(tokens.radius.md)};
  --radius-lg: ${rem(tokens.radius.lg)};
  --radius-xl: ${rem(tokens.radius.xl)};
  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);
}
`;

// ─── dist/antd.ts ─────────────────────────────────────────────────────────────────────────
const antd = {
  colorPrimary: c.primary.default,
  colorPrimaryHover: c.primary.hover,
  colorPrimaryActive: c.primary.active,
  colorPrimaryBg: c.primary.bg,
  colorInfo: c.info.default,
  colorInfoBg: c.info.bg,
  colorInfoBorder: c.info.border,
  colorLink: c.primary.default,
  colorLinkHover: c.primary.hover,
  colorLinkActive: c.primary.active,
  colorTextTertiary: c.text.tertiary,
  colorTextDescription: c.text.tertiary,
  colorTextPlaceholder: c.text.placeholder,
  colorError: c.error.default,
  colorErrorHover: c.error.hover,
  colorErrorActive: c.error.active,
  colorErrorBg: c.error.bg,
  colorErrorBorder: c.error.border,
  colorSuccess: c.success.default,
  colorSuccessBg: c.success.bg,
  colorSuccessBorder: c.success.border,
  colorWarning: c.warning.default,
  colorWarningBg: c.warning.bg,
  colorWarningBorder: c.warning.border,
  fontFamily: tokens.font.family,
  fontFamilyCode: tokens.font.familyMono,
  fontSize: tokens.font.size.base,
  borderRadius: tokens.radius.md,
  borderRadiusSM: tokens.radius.sm,
  borderRadiusLG: tokens.radius.lg,
  controlHeight: tokens.density.controlHeight,
};
const antdTs = `// Сгенерировано из packages/ui-tokens/tokens.json (v${tokens.version}) — не править руками, запускать make tokens.
// Общие токены ансамбля для темы AntD (CRM). Контраст WCAG 2.1 AA проверяет theme.test.ts.
export const RT_TOKENS = ${tsObject(antd)} as const;

/** Текст preset-тегов Tag color="green|cyan|orange" с контрастом ≥ 4.5:1 на фоне тега. */
export const RT_TAG_TEXT: Record<string, string> = ${tsObject(c.tag)};

/** Плотность таблиц: отступы ячеек обычной таблицы = small (paddingXS). */
export const RT_TABLE_CELL_PADDING = ${tokens.density.tableCellPadding};
`;

const dist = join(here, "dist");
mkdirSync(dist, { recursive: true });
writeFileSync(join(dist, "tokens.css"), tokensCss);
writeFileSync(join(dist, "shadcn.css"), shadcnCss);
writeFileSync(join(dist, "antd.ts"), antdTs);

// Копия для CRM: фронтенд CRM собирается в контейнере, куда packages/ не монтируется, поэтому файл коммитится рядом с кодом.
const crmTarget = resolve(here, "../../apps/crm/frontend/src/app/tokens.generated.ts");
if (process.argv.includes("--no-crm")) {
  console.log("dist/ готов (без копии в apps/crm)");
} else {
  writeFileSync(crmTarget, antdTs);
  console.log(`dist/ готов; CRM: ${crmTarget}`);
}
