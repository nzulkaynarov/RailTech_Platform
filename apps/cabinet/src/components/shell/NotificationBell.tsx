import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Bell, BellOff, CheckCheck, FileText, MessagesSquare, PackageCheck, Truck, Wallet, X } from 'lucide-react';

import type { PortalNotification } from '@/api/portal';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { Button } from '@/components/ui/button';
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import {
  useMarkNotificationsRead,
  useNotificationsCounterPolling,
  useNotificationsFeed,
  useNotificationsUnread,
} from '@/hooks/useNotifications';
import { formatDateTime } from '@/lib/format';
import { notificationText, safeNotificationLink } from '@/lib/notifications';
import { cn } from '@/lib/utils';

/**
 * Колокольчик кабинета (NOTIFY-2, ADR-0023 п. 2): бейдж непрочитанного из `/me`, лента — в шторке справа без ухода со
 * страницы (как `NotificationDrawer` Платформы), «Прочитать все», клик — отметка прочитанного и переход в объект.
 * Счётчик опрашивается раз в минуту и только при видимой вкладке; лента грузится при открытии шторки.
 */
export function NotificationBell() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const unread = useNotificationsUnread();
  const noteId = useId();
  useNotificationsCounterPolling();

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <button
        type="button"
        className="relative rounded-xl p-2 text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-describedby={unread > 0 ? noteId : undefined}
        title={t('notifications.title')}
        onClick={() => setOpen(true)}
      >
        <Bell className="size-5" aria-hidden="true" />
        <span className="sr-only">{t('notifications.title')}</span>
        {unread > 0 ? (
          <span
            aria-hidden="true"
            className="absolute -top-0.5 -right-0.5 inline-flex min-w-5 items-center justify-center rounded-full bg-destructive px-1.5 text-xs leading-5 font-semibold text-destructive-foreground tabular-nums"
          >
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>
      {unread > 0 ? (
        <span id={noteId} className="sr-only">
          {t('notifications.unreadNote', { count: unread })}
        </span>
      ) : null}
      <SheetContent side="right" showCloseButton={false} className="w-full gap-0 sm:max-w-md">
        {open ? <NotificationPanel onClose={() => setOpen(false)} unread={unread} /> : null}
      </SheetContent>
    </Sheet>
  );
}

function NotificationPanel({ onClose, unread }: { onClose: () => void; unread: number }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const feed = useNotificationsFeed(true);
  const mark = useMarkNotificationsRead();
  const items = feed.data?.pages.flatMap((page) => page.items) ?? [];

  const openItem = (item: PortalNotification) => {
    if (item.read_at === null) mark.mutate({ ids: [item.id] });
    onClose();
    void navigate(safeNotificationLink(item.link));
  };

  return (
    <>
      <SheetHeader className="flex-row items-start justify-between gap-2 border-b">
        <div className="flex min-w-0 flex-col gap-1">
          <SheetTitle>{t('notifications.title')}</SheetTitle>
          <SheetDescription>{t('notifications.description')}</SheetDescription>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            disabled={unread === 0 || mark.isPending}
            onClick={() => mark.mutate({ all: true })}
          >
            <CheckCheck aria-hidden="true" />
            {t('notifications.markAll')}
          </Button>
          <SheetClose
            className="rounded-md p-2 text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t('common.close')}
            title={t('common.close')}
          >
            <X className="size-4" aria-hidden="true" />
          </SheetClose>
        </div>
      </SheetHeader>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {feed.isPending ? (
          <ListSkeleton rows={3} />
        ) : feed.isError ? (
          <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
            <div className="flex size-12 items-center justify-center rounded-2xl bg-accent text-primary">
              <BellOff className="size-6" aria-hidden="true" />
            </div>
            <p className="text-base font-semibold">{t('notifications.emptyTitle')}</p>
            <p className="max-w-xs text-sm text-muted-foreground">{t('notifications.emptyText')}</p>
          </div>
        ) : (
          <>
            <ul aria-label={t('notifications.listLabel')} className="flex flex-col gap-2">
              {items.map((item) => (
                <li key={item.id}>
                  <NotificationRow item={item} onOpen={() => openItem(item)} />
                </li>
              ))}
            </ul>
            {feed.hasNextPage ? (
              <Button
                variant="outline"
                className="mt-3 w-full"
                disabled={feed.isFetchingNextPage}
                onClick={() => void feed.fetchNextPage()}
              >
                {t('notifications.more')}
              </Button>
            ) : null}
          </>
        )}
      </div>
    </>
  );
}

function NotificationRow({ item, onOpen }: { item: PortalNotification; onOpen: () => void }) {
  const { t } = useTranslation();
  const isUnread = item.read_at === null;
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'flex w-full items-start gap-3 rounded-lg border p-3 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
        isUnread ? 'border-primary/40 bg-accent/60' : 'bg-card',
      )}
    >
      <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-primary">
        <GroupIcon group={item.group} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className={cn('text-sm wrap-break-word', isUnread ? 'font-semibold' : 'text-foreground')}>
          {notificationText(item, t)}
        </span>
        <span className="text-xs text-muted-foreground">{formatDateTime(item.created_at)}</span>
      </span>
      {isUnread ? (
        <span className="mt-1.5 flex shrink-0 items-center">
          <span className="size-2 rounded-full bg-primary" aria-hidden="true" />
          <span className="sr-only">{t('notifications.unread')}</span>
        </span>
      ) : null}
    </button>
  );
}

/** Значок группы событий (документы, деньги, поставки, сообщения, товары партнёра); незнакомая — колокольчик. */
function GroupIcon({ group }: { group: string }) {
  const props = { className: 'size-4', 'aria-hidden': true } as const;
  switch (group) {
    case 'documents':
      return <FileText {...props} />;
    case 'money':
      return <Wallet {...props} />;
    case 'deliveries':
      return <Truck {...props} />;
    case 'messages':
      return <MessagesSquare {...props} />;
    case 'partner_products':
      return <PackageCheck {...props} />;
    default:
      return <Bell {...props} />;
  }
}
