import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { MessagesSquare } from 'lucide-react';

import { MESSAGES_MODULE } from '@/app/nav';
import { cn } from '@/lib/utils';
import { useUnread, useUnreadText } from '@/hooks/useUnread';
import { useHasModule } from '@/session/useMe';

/** Бейдж числа непрочитанных; 0 — ничего. Число для диктора — в подписи пункта (`nav.messagesUnread`). */
export function UnreadBadge({ count, className }: { count: number; className?: string }) {
  if (count <= 0) return null;
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex min-w-5 items-center justify-center rounded-full bg-destructive px-1.5 text-xs leading-5 font-semibold text-destructive-foreground tabular-nums',
        className,
      )}
    >
      {count > 99 ? '99+' : count}
    </span>
  );
}

/** Пояснение «Непрочитанных сообщений: N» для `aria-describedby` — вне ссылки, чтобы не войти в её имя. */
export function UnreadNote({ id, text }: { id: string; text: string | null }) {
  return text ? (
    <span id={id} className="sr-only">
      {text}
    </span>
  ) : null;
}

/** Шапка веба: «Сообщения» иконкой с бейджем — на телефоне пункт меню прячется в «Ещё». */
export function MessagesLink() {
  const { t } = useTranslation();
  const unread = useUnread();
  const text = useUnreadText(unread);
  const noteId = useId();
  if (!useHasModule(MESSAGES_MODULE)) return null;
  return (
    <>
      <Link
        to="/messages"
        className="relative rounded-xl p-2 text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
        aria-describedby={text ? noteId : undefined}
        title={text ?? t('nav.messages')}
      >
        <MessagesSquare className="size-5" aria-hidden="true" />
        <span className="sr-only">{t('nav.messages')}</span>
        <UnreadBadge count={unread} className="absolute -top-0.5 -right-0.5" />
      </Link>
      <UnreadNote id={noteId} text={text} />
    </>
  );
}
