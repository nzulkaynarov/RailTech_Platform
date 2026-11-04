import type { MouseEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageCircle } from 'lucide-react';
import { Link } from 'react-router-dom';

import { MESSAGES_MODULE } from '@/app/nav';
import type { MessageContext } from '@/api/portal';
import { Button } from '@/components/ui/button';
import { chatLink } from '@/lib/messages';
import { useHasModule } from '@/session/useMe';
import { openTelegramLink } from '@/telegram/webapp';

type Variant = 'default' | 'outline' | 'secondary' | 'ghost';

/**
 * Ссылка на бота CRM кнопкой: в вебе — настоящая ссылка в новой вкладке (открывается Telegram),
 * в Mini App — `WebApp.openTelegramLink` (переход по ссылке из webview Telegram не работает).
 */
export function TelegramLinkButton({
  href,
  children,
  variant = 'default',
  size,
  className,
  ariaLabel,
}: {
  href: string;
  children: ReactNode;
  variant?: Variant;
  size?: 'default' | 'sm' | 'icon-sm';
  className?: string;
  ariaLabel?: string;
}) {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (openTelegramLink(href)) event.preventDefault();
  };
  return (
    <Button asChild variant={variant} size={size} className={className}>
      <a href={href} target="_blank" rel="noopener noreferrer" onClick={onClick} aria-label={ariaLabel} title={ariaLabel}>
        {children}
      </a>
    </Button>
  );
}

/**
 * «Написать менеджеру» (CHAT-1, ADR-0023): чат кабинета с меткой документа (`/messages?about=…`), а не бот — общение
 * в кабинете не уводит в Telegram; бот остаётся вторым каналом на экране чата. Без модуля `messages` у сессии кнопки нет.
 *
 * `label` — полная подпись с объектом («Написать менеджеру о счёте S-2026-0124») для `aria-label`:
 * среди одинаковых кнопок списка каждая различима для диктора. `compact` — только иконка (строка
 * списка договоров, счетов, актов), подпись — в `aria-label` и подсказке.
 */
export function ManagerButton({
  context,
  label,
  compact = false,
  variant = 'outline',
  className,
}: {
  context: MessageContext | null;
  label?: string;
  compact?: boolean;
  variant?: Variant;
  className?: string;
}) {
  const { t } = useTranslation();
  if (!useHasModule(MESSAGES_MODULE)) return null;
  const ariaLabel = label ?? (compact ? t('manager.write') : undefined);
  return (
    <Button asChild variant={compact ? 'ghost' : variant} size={compact ? 'icon-sm' : 'sm'} className={className}>
      <Link to={chatLink(context)} aria-label={ariaLabel} title={ariaLabel}>
        <MessageCircle aria-hidden="true" />
        {compact ? null : t('manager.write')}
      </Link>
    </Button>
  );
}
