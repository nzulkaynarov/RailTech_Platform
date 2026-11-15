// Тест контраста WCAG 2.1 AA (1.4.3, текст ≥ 4.5:1) для пар «текст / фон» общих токенов и shadcn-переменных.
// Запуск: make -C packages/ui-tokens test (или node --test contrast.test.mjs); dist/ должен быть собран (make build).
// Пары перечислены явно: появилась новая пара «текст на фоне» в приложениях — добавьте строку сюда.
// Пары, которые SPEC-v3 §5.2 фиксирует ниже 4.5:1, вынесены в KNOWN_BELOW_AA с причиной; тест следит, чтобы они
// не падали ниже 3:1 и не «выздоравливали» молча (выздоровела — переносим в основной список).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tokens = JSON.parse(readFileSync(join(here, "tokens.json"), "utf8"));
const c = tokens.color;

// ─── WCAG 2.1: относительная яркость и контраст; полупрозрачный цвет смешивается с фоном ─────────────────
const parse = (hex) => {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  assert.ok(m, `ожидается #rrggbb, получено ${hex}`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const toHex = (rgb) => `#${rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
/** Цвет fg с прозрачностью alpha поверх bg — как его видит пользователь (Tailwind `bg-success/10`). */
const over = (fg, alpha, bg) => {
  const f = parse(fg);
  const b = parse(bg);
  return toHex(f.map((v, i) => v * alpha + b[i] * (1 - alpha)));
};
const luminance = (hex) => {
  const [r, g, b] = parse(hex).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (fg, bg) => {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
};

// ─── shadcn-переменные из dist/shadcn.css (то, что реально получают ERP и Cabinet) ───────────────────────
const shadcnCss = readFileSync(join(here, "dist", "shadcn.css"), "utf8");
const rootBlock = /:root\s*\{([^}]*)\}/.exec(shadcnCss)?.[1] ?? "";
const v = Object.fromEntries([...rootBlock.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));

// ─── токены AntD из dist/antd.ts (RT_TOKENS) — то, что реально получают CRM и Платформа ─────────────────
const antdTs = readFileSync(join(here, "dist", "antd.ts"), "utf8");
const a = Object.fromEntries([...antdTs.matchAll(/^\s+(color\w+): "(#[0-9a-f]{6})",$/gim)].map((m) => [m[1], m[2]]));

const white = c.surface.background;
const layout = c.surface.layout;

// Цвета фонов preset-тегов Ant Design (<цвет>1): текст тега — c.tag.<цвет>.
const antdTagBg = { blue: "#e6f4ff", green: "#f6ffed", cyan: "#e6fffb", orange: "#fff7e6", gold: "#fffbe6", red: "#fff1f0", purple: "#f9f0ff" };

/** [название, текст, фон] */
const pairs = [
  // Основной, вторичный и третичный текст
  ["text на белом", c.text.default, white],
  ["text на фоне окна #f5f5f5", c.text.default, layout],
  ["secondary на белом", c.text.secondary, white],
  ["secondary на фоне окна", c.text.secondary, layout],
  ["secondary на primary.bg (выбранный пункт, пузырь бота)", c.text.secondary, c.primary.bg],
  ["tertiary на белом (подписи 12 px)", c.text.tertiary, white],
  ["tertiary на фоне окна #f5f5f5", c.text.tertiary, layout],
  ["tertiary на primary.bg #e6f4ff", c.text.tertiary, c.primary.bg],
  ["tertiary на colorFillAlter #fafafa (label bordered Descriptions, Table header)", c.text.tertiary, "#fafafa"],
  ["tertiary на success.bg и warning.bg (пузыри чата CRM)", c.text.tertiary, c.success.bg],
  ["tertiary на warning.bg", c.text.tertiary, c.warning.bg],
  ["antd colorTextTertiary на colorFillAlter #fafafa", a.colorTextTertiary, "#fafafa"],
  ["antd colorTextPlaceholder на белом", a.colorTextPlaceholder, white],
  ["placeholder на белом (поля ввода)", c.text.placeholder, white],
  // Основной цвет
  ["white на кнопке primary", c.primary.foreground, c.primary.default],
  ["primary-ссылка на белом", c.primary.default, white],
  ["primary-ссылка на фоне окна", c.primary.default, layout],
  ["primary-ссылка на primary.bg", c.primary.default, c.primary.bg],
  ["primary.text на белом", c.primary.text, white],
  ["primary.text на primary.bg (активный пункт меню, вкладка)", c.primary.text, c.primary.bg],
  ["primary.text на фоне окна", c.primary.text, layout],
  ["primary.hover как текст на белом (outlined/link-кнопка при наведении)", c.primary.hover, white],
  ["primary.hover как текст на фоне окна", c.primary.hover, layout],
  ["white на primary.hover (hover кнопки primary)", c.primary.foreground, c.primary.hover],
  ["primary.active как текст на белом", c.primary.active, white],
  ["white на primary.active", c.primary.foreground, c.primary.active],
  ["info.text на белом", c.info.text, white],
  ["info.text на info.bg", c.info.text, c.info.bg],
  ["white на info", c.info.foreground, c.info.default],
  // Статусы: текст «text» — на белом и на своём светлом фоне
  ["success.text на белом", c.success.text, white],
  ["success.text на success.bg", c.success.text, c.success.bg],
  ["white на success.text (кнопка/плашка)", c.success.foreground, c.success.text],
  ["warning.text на белом", c.warning.text, white],
  ["warning.text на warning.bg", c.warning.text, c.warning.bg],
  ["white на warning.text", c.warning.foreground, c.warning.text],
  ["error.text на белом (тексты ошибок)", c.error.text, white],
  ["error.text на error.bg", c.error.text, c.error.bg],
  ["white на error.text (кнопка destructive)", c.error.foreground, c.error.text],
  ["error.hover на белом (danger-ссылка при наведении)", c.error.hover, white],
  ["white на error.hover (danger hover)", c.error.foreground, c.error.hover],
  ["white на error.active", c.error.foreground, c.error.active],
  // Теги: текст — из c.tag, фон — <цвет>1 Ant Design
  ...Object.entries(antdTagBg).map(([name, bg]) => [`тег ${name}`, c.tag[name], bg]),
  // AntD (dist/antd.ts): реальные пары компонентов. colorError/Warning/Success — цвета «text», не затравки.
  ["antd Tag error: colorError на colorErrorBg", a.colorError, a.colorErrorBg],
  ["antd Tag warning: colorWarning на colorWarningBg", a.colorWarning, a.colorWarningBg],
  ["antd Tag success: colorSuccess на colorSuccessBg", a.colorSuccess, a.colorSuccessBg],
  ["antd Form explain error: colorError на белом", a.colorError, white],
  ["antd Form explain warning: colorWarning на белом", a.colorWarning, white],
  ["antd Typography danger: colorErrorText на белом", a.colorErrorText, white],
  ["antd Button danger primary: белый на colorError", white, a.colorError],
  ["antd Button danger primary hover: белый на colorErrorHover", white, a.colorErrorHover],
  ["antd Button danger primary active: белый на colorErrorActive", white, a.colorErrorActive],
  ["antd Button danger outlined/text/link: colorError на белом", a.colorError, white],
  ["antd Button danger hover (текст): colorErrorHover на белом", a.colorErrorHover, white],
  ["antd Button danger text hover: colorErrorHover на colorErrorBg", a.colorErrorHover, a.colorErrorBg],
  ["antd Button danger active (текст): colorErrorActive на белом", a.colorErrorActive, white],
  ["antd colorErrorTextHover на белом", a.colorErrorTextHover, white],
  ["antd colorErrorTextActive на белом", a.colorErrorTextActive, white],
  ["antd Badge count: белый на colorError", white, a.colorError],
  ["antd Menu/Dropdown danger: colorError на белом", a.colorError, white],
  ["antd Menu danger selected: белый на colorError", white, a.colorError],
  ["antd Progress success: colorSuccess на белом", a.colorSuccess, white],
  ["antd colorSuccessHover на белом", a.colorSuccessHover, white],
  ["antd colorWarningHover на белом", a.colorWarningHover, white],
  ["antd colorLinkHover на белом", a.colorLinkHover, white],
  ["antd colorLinkHover на фоне окна", a.colorLinkHover, layout],
  ["antd colorLinkActive на белом", a.colorLinkActive, white],
  ["antd белый на colorPrimaryHover", white, a.colorPrimaryHover],
  ["antd colorPrimaryHover как текст на белом и на фоне окна", a.colorPrimaryHover, layout],
  ["antd colorTextDescription на фоне окна", a.colorTextDescription, a.colorBgLayout],
  // shadcn-переменные (dist/shadcn.css): пары «x-foreground на x» и текстовые роли на фонах
  ["shadcn foreground на background", v["foreground"], v["background"]],
  ["shadcn card-foreground на card", v["card-foreground"], v["card"]],
  ["shadcn popover-foreground на popover", v["popover-foreground"], v["popover"]],
  ["shadcn primary-foreground на primary", v["primary-foreground"], v["primary"]],
  ["shadcn primary-foreground на primary-hover (bg-primary-hover)", v["primary-foreground"], v["primary-hover"]],
  ["shadcn secondary-foreground на secondary", v["secondary-foreground"], v["secondary"]],
  ["shadcn accent-foreground на accent", v["accent-foreground"], v["accent"]],
  ["shadcn destructive-foreground на destructive", v["destructive-foreground"], v["destructive"]],
  ["shadcn success-foreground на success", v["success-foreground"], v["success"]],
  ["shadcn warning-foreground на warning", v["warning-foreground"], v["warning"]],
  ["shadcn info-foreground на info", v["info-foreground"], v["info"]],
  ["shadcn muted-foreground на background", v["muted-foreground"], v["background"]],
  ["shadcn muted-foreground на card", v["muted-foreground"], v["card"]],
  ["shadcn muted-foreground на muted", v["muted-foreground"], v["muted"]],
  ["shadcn muted-foreground на accent", v["muted-foreground"], v["accent"]],
  ["shadcn text-primary на background", v["primary"], v["background"]],
  ["shadcn text-destructive на background", v["destructive"], v["background"]],
  ["shadcn text-destructive на muted", v["destructive"], v["muted"]],
  ["shadcn text-success на background", v["success"], v["background"]],
  ["shadcn text-warning на background", v["warning"], v["background"]],
  ["shadcn text-info на background", v["info"], v["background"]],
  // StatusBadge Cabinet: border-X/30 bg-X/10 text-X — текст на 10 % заливке поверх белого и поверх muted
  ...["destructive", "success", "warning", "info"].map((name) => [
    `shadcn text-${name} на bg-${name}/10 (белый)`, v[name], over(v[name], 0.1, v["background"]),
  ]),
  ...["destructive", "warning", "info"].map((name) => [
    `shadcn text-${name} на bg-${name}/10 (muted)`, v[name], over(v[name], 0.1, v["muted"]),
  ]),
];

// ─── Тема кабинета (dist/cabinet.css, CAB-FIX-2): светлая :root и тёмная .dark поверх неё ──────────────────
const cabinetCss = readFileSync(join(here, "dist", "cabinet.css"), "utf8");
const cssVars = (block) => Object.fromEntries([...block.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
const cabLight = cssVars(/:root\s*\{([^}]*)\}/.exec(cabinetCss)?.[1] ?? "");
const cabDark = { ...cabLight, ...cssVars(/\.dark\s*\{([^}]*)\}/.exec(cabinetCss)?.[1] ?? "") };

/** Пары кабинета для одной темы: холст (--background) лежит на рамке и сайдбаре (--muted), активный пункт — --accent. */
const cabinetPairs = (theme, t) => {
  const surfaces = { "холст background": t["background"], "рамка и сайдбар muted": t["muted"], "card": t["card"], "accent (активный пункт)": t["accent"] };
  const rows = [];
  for (const [surface, bg] of Object.entries(surfaces)) {
    rows.push([`кабинет ${theme}: foreground на ${surface}`, t["foreground"], bg]);
    rows.push([`кабинет ${theme}: muted-foreground (подписи, группы сайдбара) на ${surface}`, t["muted-foreground"], bg]);
    rows.push([`кабинет ${theme}: text-primary (заголовки, активный пункт) на ${surface}`, t["primary"], bg]);
  }
  rows.push(
    [`кабинет ${theme}: muted-foreground на secondary`, t["muted-foreground"], t["secondary"]],
    [`кабинет ${theme}: muted-foreground на hover пункта bg-accent/60 поверх muted`, t["muted-foreground"], over(t["accent"], 0.6, t["muted"])],
    [`кабинет ${theme}: primary на hover пункта bg-accent/60 поверх muted`, t["primary"], over(t["accent"], 0.6, t["muted"])],
    [`кабинет ${theme}: primary-foreground на primary (кнопка, иконка заголовка и бара)`, t["primary-foreground"], t["primary"]],
    [`кабинет ${theme}: primary-foreground на primary-hover`, t["primary-foreground"], t["primary-hover"]],
    [`кабинет ${theme}: accent-foreground на accent`, t["accent-foreground"], t["accent"]],
    [`кабинет ${theme}: secondary-foreground на secondary`, t["secondary-foreground"], t["secondary"]],
    [`кабинет ${theme}: card-foreground на card`, t["card-foreground"], t["card"]],
    [`кабинет ${theme}: popover-foreground на popover`, t["popover-foreground"], t["popover"]],
  );
  // Статусы: заливка кнопки с текстом -foreground и бейдж StatusBadge «border-X/30 bg-X/10 text-X» на холсте и на рамке
  for (const name of ["destructive", "success", "warning", "info"]) {
    rows.push(
      [`кабинет ${theme}: ${name}-foreground на ${name}`, t[`${name}-foreground`], t[name]],
      [`кабинет ${theme}: text-${name} на холсте`, t[name], t["background"]],
      [`кабинет ${theme}: text-${name} на card`, t[name], t["card"]],
      [`кабинет ${theme}: бейдж text-${name} на bg-${name}/10 поверх холста`, t[name], over(t[name], 0.1, t["background"])],
      [`кабинет ${theme}: бейдж text-${name} на bg-${name}/10 поверх card`, t[name], over(t[name], 0.1, t["card"])],
      [`кабинет ${theme}: бейдж text-${name} на bg-${name}/10 поверх рамки muted`, t[name], over(t[name], 0.1, t["muted"])],
    );
  }
  // Бейдж neutral: text-muted-foreground на bg-muted
  rows.push([`кабинет ${theme}: бейдж neutral muted-foreground на muted`, t["muted-foreground"], t["muted"]]);
  return rows;
};
pairs.push(...cabinetPairs("светлая", cabLight), ...cabinetPairs("тёмная", cabDark));

/** Не текст (WCAG 1.4.11, ≥ 3:1): значки и точки статуса, иконка на заливке. [название, цвет, фон] */
const cabinetNonText = [cabLight, cabDark].flatMap((t, i) => {
  const theme = i ? "тёмная" : "светлая";
  return [
    [`кабинет ${theme}: точка «полномочия подтверждены» bg-success на сайдбаре muted`, t["success"], t["muted"]],
    [`кабинет ${theme}: точка «только чтение» bg-warning на сайдбаре muted`, t["warning"], t["muted"]],
    [`кабинет ${theme}: иконка text-primary-foreground в плитке bg-primary`, t["primary-foreground"], t["primary"]],
    [`кабинет ${theme}: кольцо фокуса ring на холсте`, t["ring"], t["background"]],
    [`кабинет ${theme}: кольцо фокуса ring на рамке muted`, t["ring"], t["muted"]],
  ];
});

// Пары ниже 4.5:1, которые фиксирует SPEC-v3 §5.2 или действующие компоненты. Вопросы — docs/QUESTIONS.md, Q-INF-P0-2-*.
// С палитрой стандарта интерфейса (0.3.0) исключений нет: обе прежние пары проходят и стоят в основном списке.
const KNOWN_BELOW_AA = [];
pairs.push(
  ["white на shadcn bg-primary/90 (hover кнопок)", v["primary-foreground"], over(v["primary"], 0.9, v["background"])],
  ["shadcn text-success на bg-success/10 (muted)", v["success"], over(v["success"], 0.1, v["muted"])],
);

test("эталонные значения контраста", () => {
  assert.ok(Math.abs(contrast("#000000", "#ffffff") - 21) < 0.01);
  assert.ok(Math.abs(contrast("#6e6e6e", "#ffffff") - 5.10) < 0.01);
  assert.ok(Math.abs(contrast("#5f6f86", "#f1f5f9") - 4.67) < 0.02);
  assert.ok(Math.abs(contrast("#1677ff", "#ffffff") - 4.1) < 0.05);
});

test("версия пакета 0.3.0", () => {
  assert.equal(tokens.version, "0.3.0");
});

test("значения стандарта интерфейса §2 (docs/architecture/ui-standard.md)", () => {
  assert.deepEqual(
    [c.primary.default, c.primary.hover, c.primary.bg, c.primary.text],
    ["#1d4ed8", "#1e40af", "#eff6ff", "#1d4ed8"],
  );
  // Текст «готово» и «ждёт» — ступень 800: ступень 700 на 10-процентной заливке бейджа даёт 4,0–4,4:1
  assert.deepEqual([c.success.default, c.success.text], ["#16a34a", "#166534"]);
  assert.deepEqual([c.warning.default, c.warning.text], ["#d97706", "#92400e"]);
  assert.deepEqual([c.error.default, c.error.text], ["#e11d48", "#be123c"]);
  assert.deepEqual([c.tag.purple, c.tag.cyan], ["#6d28d9", "#0e7490"]);
  // Приглушённый текст — не #94a3b8 исходного документа (2,56:1) и не #64748b (4,34:1 на вторичной поверхности)
  assert.deepEqual([c.text.default, c.text.secondary, c.text.tertiary], ["#0f172a", "#475569", "#5f6f86"]);
  assert.deepEqual([c.surface.border, c.surface.control, c.surface.split], ["#e2e8f0", "#cbd5e1", "#f1f5f9"]);
  assert.deepEqual([c.surface.layout, c.surface.background], ["#f8fafc", "#ffffff"]);
  assert.deepEqual([c.action.default, c.action.foreground], ["#0f172a", "#ffffff"]);
  assert.deepEqual([tokens.radius.md, tokens.radius.lg], [6, 8]);
  assert.equal(tokens.font.family, `'Inter Variable', Inter, -apple-system, "Segoe UI", Roboto, Arial, sans-serif`);
});

test("AntD: статусные цвета — «text», затравки только в RT_STATUS_FILL", () => {
  assert.equal(a.colorError, c.error.text);
  assert.equal(a.colorWarning, c.warning.text);
  assert.equal(a.colorSuccess, c.success.text);
  assert.equal(a.colorPrimaryHover, "#1e40af");
  assert.match(antdTs, /RT_STATUS_FILL = \{\n  error: "#e11d48",\n  warning: "#d97706",\n  success: "#16a34a",/);
});

test("затравочные цвета статусов не попадают в текст shadcn", () => {
  assert.equal(v["destructive"], c.error.text);
  assert.equal(v["success"], c.success.text);
  assert.equal(v["warning"], c.warning.text);
});

test("тема кабинета только переопределяет переменные shadcn и не трогает shadcn.css (ERP)", () => {
  assert.deepEqual(Object.keys(cabLight).sort(), Object.keys(v).sort());
  assert.equal(v["primary"], c.primary.default);
  assert.equal(cabLight["primary"], tokens.shadcnThemes.cabinet.light.primary);
  for (const key of Object.keys(cabDark)) assert.ok(key in v, `.dark: --${key} нет в shadcn.css`);
});

for (const [name, fg, bg] of pairs) {
  test(`${name} ≥ 4.5:1`, () => {
    const ratio = contrast(fg, bg);
    assert.ok(ratio >= 4.5, `${name}: ${fg} на ${bg} = ${ratio.toFixed(2)}:1`);
  });
}

for (const [name, fg, bg] of cabinetNonText) {
  test(`${name} ≥ 3:1`, () => {
    const ratio = contrast(fg, bg);
    assert.ok(ratio >= 3, `${name}: ${fg} на ${bg} = ${ratio.toFixed(2)}:1`);
  });
}

for (const [name, fg, bg] of KNOWN_BELOW_AA) {
  test(`известное исключение: ${name} в пределах 3:1…4.5:1`, () => {
    const ratio = contrast(fg, bg);
    assert.ok(ratio >= 3, `${name}: ${ratio.toFixed(2)}:1 < 3:1`);
    assert.ok(ratio < 4.5, `${name}: ${ratio.toFixed(2)}:1 теперь проходит — перенесите пару в основной список`);
  });
}
