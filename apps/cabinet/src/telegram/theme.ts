import type { TelegramThemeParams, TelegramWebApp } from './webapp';

/**
 * Тема Telegram поверх семантических переменных shadcn (CONVENTIONS.md §3): компоненты не знают о
 * Telegram, меняются только `--background`, `--primary`… на `<html>`. Переменные, которых
 * в `themeParams` нет, остаются из `packages/ui-tokens`.
 */
const THEME_MAP: Array<[keyof TelegramThemeParams, string[]]> = [
  ['bg_color', ['--background', '--popover']],
  ['text_color', ['--foreground', '--card-foreground', '--popover-foreground', '--secondary-foreground']],
  ['secondary_bg_color', ['--muted', '--secondary']],
  ['section_bg_color', ['--card']],
  ['hint_color', ['--muted-foreground']],
  ['button_color', ['--primary', '--ring']],
  ['button_text_color', ['--primary-foreground']],
  ['accent_text_color', ['--accent-foreground']],
  ['section_separator_color', ['--border', '--input']],
  ['destructive_text_color', ['--destructive']],
];

const HEX_RE = /^#[0-9a-f]{3,8}$/i;

export function applyTelegramTheme(webApp: TelegramWebApp, root: HTMLElement = document.documentElement): void {
  const params = webApp.themeParams ?? {};
  for (const [param, variables] of THEME_MAP) {
    const value = params[param];
    if (!value || !HEX_RE.test(value)) continue;
    for (const variable of variables) root.style.setProperty(variable, value);
  }
  const dark = webApp.colorScheme === 'dark';
  root.classList.toggle('dark', dark);
  root.style.colorScheme = dark ? 'dark' : 'light';
}

/** Готовность Mini App: сообщить Telegram, развернуть на весь экран, применить и отслеживать тему. */
export function initMiniApp(webApp: TelegramWebApp): void {
  root().dataset.mode = 'miniapp';
  applyTelegramTheme(webApp);
  webApp.onEvent?.('themeChanged', () => applyTelegramTheme(webApp));
  webApp.ready();
  webApp.expand();
}

function root(): HTMLElement {
  return document.documentElement;
}
