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
  ["tertiary на белом (подписи 12 px — только на белых карточках)", c.text.tertiary, white],
  ["placeholder на белом (поля ввода)", c.text.placeholder, white],
  // Основной цвет
  ["white на кнопке primary", c.primary.foreground, c.primary.default],
  ["primary-ссылка на белом", c.primary.default, white],
  ["primary-ссылка на фоне окна", c.primary.default, layout],
  ["primary-ссылка на primary.bg", c.primary.default, c.primary.bg],
  ["primary.text на белом", c.primary.text, white],
  ["primary.text на primary.bg (активный пункт меню, вкладка)", c.primary.text, c.primary.bg],
  ["primary.text на фоне окна", c.primary.text, layout],
  ["link hover / active (primary.text) на белом", c.primary.text, white],
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
  // shadcn-переменные (dist/shadcn.css): пары «x-foreground на x» и текстовые роли на фонах
  ["shadcn foreground на background", v["foreground"], v["background"]],
  ["shadcn card-foreground на card", v["card-foreground"], v["card"]],
  ["shadcn popover-foreground на popover", v["popover-foreground"], v["popover"]],
  ["shadcn primary-foreground на primary", v["primary-foreground"], v["primary"]],
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

// Пары ниже 4.5:1, которые фиксирует SPEC-v3 §5.2 (значения заданы владельцем). Вопросы — docs/QUESTIONS.md, Q-INF-P0-2-*.
const KNOWN_BELOW_AA = [
  ["white на primary.hover #1677ff (hover кнопки primary, Q-INF-P0-2-1)", c.primary.foreground, c.primary.hover],
  ["white на shadcn bg-primary/90 (hover кнопок Cabinet, Q-INF-P0-2-1)", v["primary-foreground"], over(v["primary"], 0.9, v["background"])],
  ["white на error.default #ff4d4f (solid danger-кнопка AntD, бейдж очереди, Q-INF-P0-2-2)", c.error.foreground, c.error.default],
  ["текст ошибки colorError #ff4d4f на белом (Typography danger, ошибки Form AntD, Q-INF-P0-2-2)", c.error.default, white],
  ["tertiary на фоне окна #f5f5f5 (Q-INF-P0-2-3)", c.text.tertiary, layout],
  ["tertiary на primary.bg #e6f4ff (Q-INF-P0-2-3)", c.text.tertiary, c.primary.bg],
  ["shadcn text-success на bg-success/10 поверх muted #f5f5f5 (4.49:1, Q-INF-P0-2-3)", v["success"], over(v["success"], 0.1, v["muted"])],
];

test("эталонные значения контраста", () => {
  assert.ok(Math.abs(contrast("#000000", "#ffffff") - 21) < 0.01);
  assert.ok(Math.abs(contrast("#767676", "#ffffff") - 4.54) < 0.01);
  assert.ok(Math.abs(contrast("#1677ff", "#ffffff") - 4.1) < 0.05);
});

test("версия пакета 0.2.0", () => {
  assert.equal(tokens.version, "0.2.0");
});

test("значения SPEC-v3 §5.2 / 03-frontend.md §3", () => {
  assert.deepEqual(
    [c.primary.default, c.primary.hover, c.primary.bg, c.primary.text],
    ["#1668dc", "#1677ff", "#e6f4ff", "#0958d9"],
  );
  assert.deepEqual([c.success.default, c.success.text], ["#52c41a", "#237804"]);
  assert.deepEqual([c.warning.default, c.warning.text], ["#faad14", "#874d00"]);
  assert.deepEqual([c.error.default, c.error.text], ["#ff4d4f", "#a8071a"]);
  assert.deepEqual([c.tag.purple, c.tag.cyan], ["#531dab", "#006d75"]);
  assert.deepEqual([c.text.default, c.text.secondary, c.text.tertiary], ["#1f1f1f", "#595959", "#767676"]);
  assert.deepEqual([c.surface.border, c.surface.split], ["#d9d9d9", "#f0f0f0"]);
  assert.deepEqual([c.surface.layout, c.surface.background], ["#f5f5f5", "#ffffff"]);
  assert.deepEqual([tokens.radius.md, tokens.radius.lg], [6, 8]);
  assert.equal(tokens.font.family, 'Inter, -apple-system, "Segoe UI", Roboto, Arial, sans-serif');
});

test("затравочные цвета статусов не попадают в текст shadcn", () => {
  assert.equal(v["destructive"], c.error.text);
  assert.equal(v["success"], c.success.text);
  assert.equal(v["warning"], c.warning.text);
});

for (const [name, fg, bg] of pairs) {
  test(`${name} ≥ 4.5:1`, () => {
    const ratio = contrast(fg, bg);
    assert.ok(ratio >= 4.5, `${name}: ${fg} на ${bg} = ${ratio.toFixed(2)}:1`);
  });
}

for (const [name, fg, bg] of KNOWN_BELOW_AA) {
  test(`известное исключение: ${name} в пределах 3:1…4.5:1`, () => {
    const ratio = contrast(fg, bg);
    assert.ok(ratio >= 3, `${name}: ${ratio.toFixed(2)}:1 < 3:1`);
    assert.ok(ratio < 4.5, `${name}: ${ratio.toFixed(2)}:1 теперь проходит — перенесите пару в основной список`);
  });
}
