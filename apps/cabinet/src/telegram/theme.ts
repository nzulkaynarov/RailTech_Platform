import tokensCss from '@/styles/tokens.generated.css?raw';
import { contrastRatio, normalizeHex, over } from '@/lib/contrast';
import type { TelegramThemeParams, TelegramWebApp } from './webapp';

/**
 * Тема Telegram поверх семантических переменных shadcn (CONVENTIONS.md §3): компоненты не знают о Telegram, меняются
 * только `--background`, `--primary`… на `<html>`. Основа — тема кабинета из `packages/ui-tokens` (светлая или `.dark`).
 *
 * **Цвет Telegram берётся, только если с ним все пары проходят AA** (CAB-FIX-3): текст ≥ 4.5:1 против фонов (холст,
 * рамка, карточка, активный пункт, 10 % заливки статусов), значки и кольцо фокуса ≥ 3:1 — те же пары, что
 * `packages/ui-tokens/contrast.test.mjs` проверяет у наших тем. Иначе остаётся наш токен. Стандартные темы Telegram
 * не держат AA у `button_color` с белым текстом (4,1:1 и 3,6:1) и у `hint_color` (≈ 4,2–4,4:1) — там остаются наши
 * основной цвет и подписи, а фоны и текст Telegram ложатся.
 *
 * Группы применяются по порядку (сначала фоны, потом тексты), группа — целиком или никак: кнопка и её текст — пара.
 */
const GROUPS: Array<Array<[keyof TelegramThemeParams, string[]]>> = [
  [['bg_color', ['--background', '--popover']]],
  [['secondary_bg_color', ['--muted', '--secondary']]],
  [['section_bg_color', ['--card']]],
  [['text_color', ['--foreground', '--card-foreground', '--popover-foreground', '--secondary-foreground']]],
  [['hint_color', ['--muted-foreground']]],
  [
    ['button_color', ['--primary', '--primary-hover', '--ring']],
    ['button_text_color', ['--primary-foreground']],
  ],
  [['accent_text_color', ['--accent-foreground']]],
  [['section_separator_color', ['--border', '--input']]],
  [['destructive_text_color', ['--destructive']]],
];

export const TELEGRAM_VARIABLES = GROUPS.flat().flatMap(([, variables]) => variables);

export type Palette = Record<string, string>;

function cssBlock(selector: RegExp): Palette {
  const block = selector.exec(tokensCss)?.[1] ?? '';
  const palette: Palette = {};
  for (const [, name, value] of block.matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
    const hex = normalizeHex(value);
    if (hex) palette[name] = hex;
  }
  return palette;
}

/** Палитры кабинета из `tokens.generated.css` (копия `packages/ui-tokens/dist/cabinet.css`): светлая и тёмная. */
export function cabinetPalette(scheme: 'light' | 'dark'): Palette {
  const light = cssBlock(/:root\s*\{([^}]*)\}/);
  return scheme === 'dark' ? { ...light, ...cssBlock(/\.dark\s*\{([^}]*)\}/) } : light;
}

/** Пары «цвет на фоне» с порогом: текст 4.5, значки и кольцо 3. */
export function palettePairs(p: Palette): Array<[name: string, fg: string, bg: string, min: number]> {
  const surfaces: Array<[string, string]> = [
    ['background', p['--background']],
    ['muted', p['--muted']],
    ['card', p['--card']],
    ['accent', p['--accent']],
    ['secondary', p['--secondary']],
    ['accent/60 на muted', over(p['--accent'], 0.6, p['--muted'])],
  ];
  const rows: Array<[string, string, string, number]> = [];
  for (const [surface, bg] of surfaces) {
    rows.push([`foreground на ${surface}`, p['--foreground'], bg, 4.5]);
    rows.push([`muted-foreground на ${surface}`, p['--muted-foreground'], bg, 4.5]);
    rows.push([`primary на ${surface}`, p['--primary'], bg, 4.5]);
  }
  rows.push(
    ['card-foreground на card', p['--card-foreground'], p['--card'], 4.5],
    ['popover-foreground на popover', p['--popover-foreground'], p['--popover'], 4.5],
    ['secondary-foreground на secondary', p['--secondary-foreground'], p['--secondary'], 4.5],
    ['primary-foreground на primary', p['--primary-foreground'], p['--primary'], 4.5],
    ['primary-foreground на primary-hover', p['--primary-foreground'], p['--primary-hover'], 4.5],
    ['accent-foreground на accent', p['--accent-foreground'], p['--accent'], 4.5],
    ['ring на background', p['--ring'], p['--background'], 3],
    ['ring на muted', p['--ring'], p['--muted'], 3],
  );
  for (const name of ['destructive', 'success', 'warning', 'info']) {
    const color = p[`--${name}`];
    rows.push([`${name}-foreground на ${name}`, p[`--${name}-foreground`], color, 4.5]);
    for (const surface of ['--background', '--card', '--muted']) {
      rows.push([`${name} на ${surface}`, color, p[surface], 4.5]);
      rows.push([`${name} на ${name}/10 поверх ${surface}`, color, over(color, 0.1, p[surface]), 4.5]);
    }
  }
  return rows;
}

export function paletteProblems(palette: Palette): string[] {
  return palettePairs(palette)
    .filter(([, fg, bg, min]) => !fg || !bg || contrastRatio(fg, bg) < min)
    .map(([name, fg, bg]) => `${name}: ${fg} на ${bg}`);
}

/**
 * Какие цвета Telegram лягут на переменные: группа принимается, если с ней палитра проходит все пары.
 * `applied` — переменные и значения, `rejected` — параметры Telegram, оставившие наш токен.
 */
export function telegramPalette(
  params: TelegramThemeParams,
  scheme: 'light' | 'dark',
): { palette: Palette; applied: Palette; rejected: Array<keyof TelegramThemeParams> } {
  let palette = cabinetPalette(scheme);
  const applied: Palette = {};
  const rejected: Array<keyof TelegramThemeParams> = [];
  for (const group of GROUPS) {
    const patch: Palette = {};
    const present = group.filter(([param]) => normalizeHex(params[param]));
    if (present.length === 0) continue;
    for (const [param, variables] of present) {
      for (const variable of variables) patch[variable] = normalizeHex(params[param]) as string;
    }
    const candidate = { ...palette, ...patch };
    if (paletteProblems(candidate).length === 0) {
      palette = candidate;
      Object.assign(applied, patch);
    } else {
      rejected.push(...present.map(([param]) => param));
    }
  }
  return { palette, applied, rejected };
}

export function applyTelegramTheme(webApp: TelegramWebApp, root: HTMLElement = document.documentElement): void {
  const dark = webApp.colorScheme === 'dark';
  root.classList.toggle('dark', dark);
  root.style.colorScheme = dark ? 'dark' : 'light';
  for (const variable of TELEGRAM_VARIABLES) root.style.removeProperty(variable);
  const { applied } = telegramPalette(webApp.themeParams ?? {}, dark ? 'dark' : 'light');
  for (const [variable, value] of Object.entries(applied)) root.style.setProperty(variable, value);
}

/** Готовность Mini App: сообщить Telegram, развернуть на весь экран, применить и отслеживать тему. */
export function initMiniApp(webApp: TelegramWebApp): void {
  document.documentElement.dataset.mode = 'miniapp';
  applyTelegramTheme(webApp);
  webApp.onEvent?.('themeChanged', () => applyTelegramTheme(webApp));
  webApp.ready();
  webApp.expand();
}
