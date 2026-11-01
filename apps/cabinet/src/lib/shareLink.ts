/**
 * Ссылка на текущую страницу для коллеги (CAB-FIX-3, K15): `origin + pathname` и параметры адреса, если они не служебные.
 * Без `#…` (в нём magic-токен входа и `tgWebAppData` Telegram) и без служебных параметров — подписанные данные Telegram
 * и токены не уходят из кабинета вместе со ссылкой.
 */
const SERVICE_PARAM = /^(tgwebapp|token$|startapp$|start_param$|utm_)/i;

export function shareableUrl(location: Pick<Location, 'origin' | 'pathname' | 'search'>): string {
  const params = new URLSearchParams(location.search);
  for (const name of [...params.keys()]) if (SERVICE_PARAM.test(name)) params.delete(name);
  const search = params.toString();
  return `${location.origin}${location.pathname}${search ? `?${search}` : ''}`;
}

/** Копирует текст в буфер; `false` — буфер недоступен или запрещён (сообщение показывает вызывающий). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
