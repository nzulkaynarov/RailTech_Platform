import type { MouseEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageCircle } from 'lucide-react';

import { managerLink } from '@/app/links';
import { Button } from '@/components/ui/button';
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
 * «Написать менеджеру» (M2-CAB-03): `t.me/<бот>?start=deal_<id>` — бот CRM получает контекст сделки.
 * Без имени бота (`VITE_BOT_USERNAME` пуст) кнопки нет — не битая ссылка.
 *
 * `label` — полная подпись с объектом («Написать менеджеру о счёте S-2026-0124») для `aria-label`:
 * среди одинаковых кнопок списка каждая различима для диктора. `compact` — только иконка (строка
 * списка договоров, счетов, актов), подпись — в `aria-label` и подсказке.
 */
export function ManagerButton({
  dealId,
  label,
  compact = false,
  variant = 'outline',
  className,
}: {
  dealId: number | null | undefined;
  label?: string;
  compact?: boolean;
  variant?: Variant;
  className?: string;
}) {
  const { t } = useTranslation();
  const href = managerLink(dealId);
  if (!href) return null;
  return (
    <TelegramLinkButton
      href={href}
      variant={compact ? 'ghost' : variant}
      size={compact ? 'icon-sm' : 'sm'}
      className={className}
      ariaLabel={label ?? (compact ? t('manager.write') : undefined)}
    >
      <MessageCircle aria-hidden="true" />
      {compact ? null : t('manager.write')}
    </TelegramLinkButton>
  );
}
