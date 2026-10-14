/**
 * Ссылки на бота CRM. Имя бота — `VITE_BOT_USERNAME` (без @, не секрет). Пусто → кнопки скрыты.
 * `start=web` — метка «пришёл с сайта» для лида (ARCHITECTURE §17); `deal_<id>` — M2-CAB-03.
 */
export function botLink(start?: string): string | null {
  const username = (import.meta.env.VITE_BOT_USERNAME ?? '').replace(/^@/, '').trim();
  if (!username) return null;
  const url = new URL(`https://t.me/${username}`);
  if (start) url.searchParams.set('start', start);
  return url.toString();
}

/** dev-мок портального API включён (только dev-сборка). */
export function isPortalMock(): boolean {
  return import.meta.env.DEV && import.meta.env.VITE_PORTAL_MOCK === '1';
}
