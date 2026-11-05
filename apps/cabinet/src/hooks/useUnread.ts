import { useTranslation } from 'react-i18next';

import { MESSAGES_MODULE } from '@/app/nav';
import { useHasModule, useMe } from '@/session/useMe';

/** Непрочитанные контактом ответы менеджера (`/me.unread`, CHAT-1); нет модуля `messages` — 0. */
export function useUnread(): number {
  const unread = useMe().data?.unread ?? 0;
  return useHasModule(MESSAGES_MODULE) ? unread : 0;
}

/**
 * Пояснение к пункту «Сообщения» для диктора («Непрочитанных сообщений: 2») — в `aria-describedby`, а не в имени:
 * имя ссылки остаётся видимой подписью (axe `label-content-name-mismatch`); нет непрочитанных — `null`.
 */
export function useUnreadText(count: number): string | null {
  const { t } = useTranslation();
  return count > 0 ? t('nav.unread', { count }) : null;
}
