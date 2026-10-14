/**
 * Telegram Web App SDK (`telegram-web-app.js` из index.html) — только то, что нужно Cabinet.
 * Это типы внешнего SDK, а не ответов API: ответы портала типизирует только `src/api/portal.d.ts`.
 *
 * Режим определяется по `initData`: SDK создаёт `window.Telegram.WebApp` и в обычном браузере,
 * но подписанные данные пользователя есть только внутри Telegram.
 */

export interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
  header_bg_color?: string;
  bottom_bar_bg_color?: string;
  accent_text_color?: string;
  section_bg_color?: string;
  section_header_text_color?: string;
  section_separator_color?: string;
  subtitle_text_color?: string;
  destructive_text_color?: string;
}

export interface TelegramBackButton {
  isVisible: boolean;
  show(): void;
  hide(): void;
  onClick(callback: () => void): void;
  offClick(callback: () => void): void;
}

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    start_param?: string;
    user?: { id: number; first_name?: string; language_code?: string };
  };
  colorScheme: 'light' | 'dark';
  themeParams: TelegramThemeParams;
  platform?: string;
  BackButton?: TelegramBackButton;
  ready(): void;
  expand(): void;
  openTelegramLink?(url: string): void;
  onEvent?(event: 'themeChanged', handler: () => void): void;
  offEvent?(event: 'themeChanged', handler: () => void): void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

/** Объект SDK, если скрипт загрузился (в браузере он тоже есть, но без `initData`). */
export function getTelegramWebApp(): TelegramWebApp | undefined {
  if (typeof window === 'undefined') return undefined;
  return window.Telegram?.WebApp;
}

/** Открыто ли приложение как Mini App: есть подписанная строка `initData`. */
export function isMiniApp(): boolean {
  return Boolean(getTelegramWebApp()?.initData);
}

/** Строка `initData` как есть — уходит в `POST /auth/telegram`, подпись проверяет ERP. */
export function getInitData(): string {
  return getTelegramWebApp()?.initData ?? '';
}

export function getStartParam(): string | undefined {
  return getTelegramWebApp()?.initDataUnsafe.start_param || undefined;
}
