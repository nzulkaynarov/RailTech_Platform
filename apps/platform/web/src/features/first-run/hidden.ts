/**
 * «Скрыть» баннер настройки запоминается в браузере администратора (`localStorage`, по его id): это удобство одного
 * браузера, а не данные. Хранилище недоступно — баннер скрыт до перезагрузки.
 */
const PREFIX = "rt-pf-setup-banner-hidden:";
const inMemory = new Set<string>();

export function isBannerHidden(userId: string): boolean {
  if (inMemory.has(userId)) return true;
  try {
    return window.localStorage.getItem(PREFIX + userId) === "1";
  } catch {
    return false;
  }
}

export function hideBanner(userId: string): void {
  inMemory.add(userId);
  try {
    window.localStorage.setItem(PREFIX + userId, "1");
  } catch {
    // Останется скрытым до перезагрузки страницы.
  }
}

export function resetBannerHidden(userId: string): void {
  inMemory.delete(userId);
  try {
    window.localStorage.removeItem(PREFIX + userId);
  } catch {
    // Нечего очищать.
  }
}
