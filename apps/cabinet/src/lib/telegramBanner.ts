/**
 * «Позже» на плашке «Подключите Telegram» (ADR-0023 п. 3): плашка прячется на 14 дней в этом браузере.
 * Это удобство одного устройства, не настройка контакта, поэтому — localStorage; недоступное хранилище (приватный режим)
 * значит «плашку показывать», а не ошибку.
 */
export const TELEGRAM_BANNER_SNOOZE_KEY = 'rt-cab-tg-banner-snooze';
export const TELEGRAM_BANNER_SNOOZE_MS = 14 * 24 * 60 * 60 * 1000;

export function bannerSnoozed(now: number): boolean {
  try {
    const until = Number(localStorage.getItem(TELEGRAM_BANNER_SNOOZE_KEY));
    return Number.isFinite(until) && until > now;
  } catch {
    return false;
  }
}

export function snoozeBanner(now: number): void {
  try {
    localStorage.setItem(TELEGRAM_BANNER_SNOOZE_KEY, String(now + TELEGRAM_BANNER_SNOOZE_MS));
  } catch {
    // Хранилище недоступно — плашка скрыта до перезагрузки страницы.
  }
}
