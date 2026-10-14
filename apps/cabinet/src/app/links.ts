/**
 * Ссылки на бота CRM. Имя бота — `VITE_BOT_USERNAME` (без @, не секрет). Пусто → кнопки скрыты.
 * `start=web` — метка «пришёл с сайта» для лида (ARCHITECTURE §17); `start=deal_<id>` — «Написать
 * менеджеру» с контекстом сделки (M2-CAB-03): бот CRM получает `/start deal_<id>`.
 */
export function botLink(start?: string): string | null {
  const username = (import.meta.env.VITE_BOT_USERNAME ?? '').replace(/^@/, '').trim();
  if (!username) return null;
  const url = new URL(`https://t.me/${username}`);
  if (start) url.searchParams.set('start', start);
  return url.toString();
}

/** Параметр `start` бота для сделки: `deal_<id>` (тот же формат, что deep-link Mini App). */
export function dealStartParam(dealId: number): string {
  return `deal_${dealId}`;
}

/**
 * «Написать менеджеру»: `https://t.me/<бот>?start=deal_<id>`. Без сделки (КП ещё не привязано) —
 * просто чат с ботом, без контекста; без имени бота — `null` (кнопку не показываем, не битая ссылка).
 */
export function managerLink(dealId: number | null | undefined): string | null {
  const hasDeal = typeof dealId === 'number' && Number.isInteger(dealId) && dealId > 0;
  return botLink(hasDeal ? dealStartParam(dealId) : undefined);
}

/** dev-мок портального API включён (только dev-сборка). */
export function isPortalMock(): boolean {
  return import.meta.env.DEV && import.meta.env.VITE_PORTAL_MOCK === '1';
}
