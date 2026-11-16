import { useQuery } from '@tanstack/react-query';

import { getOperator } from '@/api/portal';

/**
 * Ссылки на бота CRM. Имя бота — из `GET /operator` (`bot_username`): единственный источник — CRM (процесс бота узнаёт
 * имя у Telegram), ERP держит проекцию. Своей настройки сборки у кабинета нет. Имени нет → кнопки скрыты.
 * `start=web` — метка «пришёл с сайта» для лида (ARCHITECTURE §17). «Написать менеджеру» — чат кабинета
 * (`lib/messages.ts`, CHAT-1); бот — второй канал: вход, «Я новый клиент», ссылка на экране чата.
 */
export function botUrl(username: string | null | undefined, start?: string): string | null {
  const name = (username ?? '').replace(/^@/, '').trim();
  if (!name) return null;
  const url = new URL(`https://t.me/${name}`);
  if (start) url.searchParams.set('start', start);
  return url.toString();
}

/** Ссылка на бота для экрана; тот же запрос, что название оператора (`['operator']`), — один запрос на кабинет. */
export function useBotLink(start?: string): string | null {
  const operator = useQuery({ queryKey: ['operator'], queryFn: getOperator, staleTime: 10 * 60_000, retry: false });
  return botUrl(operator.data?.bot_username, start);
}

/** dev-мок портального API включён (только dev-сборка). */
export function isPortalMock(): boolean {
  return import.meta.env.DEV && import.meta.env.VITE_PORTAL_MOCK === '1';
}
