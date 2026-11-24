import type { ReactNode } from 'react';
import { Link, type To } from 'react-router-dom';
import { MoreHorizontal, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

/**
 * Меню строки «⋯»: вторичные действия строки списка (скачать, написать менеджеру, повторить) — в одном меню, а не
 * кнопкой в каждой строке. Главное действие строки (подписать, оплатить, принять) остаётся видимой кнопкой.
 * `name` — номер или название строки для подписи кнопки диктору («Действия: S-2026-0124»).
 * Пунктами служат `RowMenuLink` и `RowMenuAction`; без единого пункта меню не рисуется.
 */
export function RowMenu({ name, children }: { name: string; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={t('common.rowMenu', { name })} title={t('common.actions')}>
          <MoreHorizontal aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">{children}</DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Пункт-ссылка: переход по адресу (клавиатура — как у обычной ссылки). */
export function RowMenuLink({
  to,
  state,
  icon: Icon,
  ariaLabel,
  children,
}: {
  to: To;
  state?: unknown;
  /** Полная подпись с объектом для диктора (в списке из нескольких одинаковых пунктов). */
  ariaLabel?: string;
  icon?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <DropdownMenuItem asChild>
      <Link to={to} state={state} aria-label={ariaLabel}>
        {Icon ? <Icon aria-hidden="true" /> : null}
        {children}
      </Link>
    </DropdownMenuItem>
  );
}

/** Пункт-действие: вызов обработчика (скачивание, открытие окна). */
export function RowMenuAction({
  onSelect,
  icon: Icon,
  disabled,
  destructive,
  children,
}: {
  onSelect: () => void;
  icon?: LucideIcon;
  disabled?: boolean;
  /** Опасное действие (отключить, удалить): красный пункт. */
  destructive?: boolean;
  children: ReactNode;
}) {
  return (
    <DropdownMenuItem disabled={disabled} variant={destructive ? 'destructive' : 'default'} onSelect={onSelect}>
      {Icon ? <Icon aria-hidden="true" /> : null}
      {children}
    </DropdownMenuItem>
  );
}
