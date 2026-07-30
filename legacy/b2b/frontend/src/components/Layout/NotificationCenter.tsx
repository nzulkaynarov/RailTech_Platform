import React, { useState, useEffect, useCallback, useRef } from 'react';
import { authedWsUrl } from '@/lib/ws';
import { useTranslation } from 'react-i18next';
import { Bell, Info, AlertTriangle, CheckCircle, Clock, Check, ExternalLink, BellOff } from 'lucide-react';
import { notificationsApi, Notification } from '@/api/notificationsApi';
import { formatDistanceToNow } from 'date-fns';
import { ru, enUS } from 'date-fns/locale';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/store/authStore';
import { getAccessToken } from '@/api/accessToken';
import { useUserStore } from '@/store/userStore';

import {
    Sheet,
    SheetTrigger,
    SheetContent,
    SheetHeader,
    SheetTitle,
    SheetDescription,
    SheetFooter,
    SheetClose,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';

const getTypeIcon = (type: string) => {
    switch (type) {
        case 'WARNING': case 'ERROR': return AlertTriangle;
        case 'SUCCESS': return CheckCircle;
        default: return Info;
    }
};

const getTypeColor = (type: string, isRead: boolean) => {
    if (isRead) return 'text-muted-foreground bg-muted border-border';
    switch (type) {
        case 'WARNING': return 'text-warning bg-warning/10 border-warning/20';
        case 'ERROR':   return 'text-destructive bg-destructive/10 border-destructive/20';
        case 'SUCCESS': return 'text-success bg-success/10 border-success/20';
        default:        return 'text-primary bg-primary/10 border-primary/20';
    }
};

interface NotificationCenterProps {
    triggerOnly?: boolean;
    // AppShell passes its hash-navigation callback so a notification opens the right
    // in-app page (no full-page reload to /crm or /cabinet shells the buyer/seller
    // don't use). When absent (e.g. router shells) we fall back to the raw link.
    onNavigate?: (pageId: string) => void;
}

// Where a notification click should land the user. N1: a deal-scoped notification
// DEEP-LINKS to the deal WORKSPACE (where the КП / contract / chat live) using the
// `deal` id the backend already sends — instead of the generic /crm/deals *list* the
// legacy `link` field encoded (which dropped the user with no way to find the document
// the alert was about). Returns a hash route for deal notifications, or a plain AppShell
// page id for the rest (profile / KYC). Seller lands in the КП builder, buyer in the
// request detail — both show the deal's documents in context.
function notificationTarget(n: Notification, activeStatus: string): { hash?: string; page?: string } {
    const isSeller = activeStatus === 'SELLER';
    // F2: ссылка, начинающаяся с «#», — точный маршрут SPA, который бэкенд поставил осознанно
    // («вот ЭТОТ счёт»). Она обязана иметь приоритет над выводом по сделке: иначе уведомление
    // «оплата получена» приводило на карточку сделки вообще, и человек шёл искать документ,
    // о котором его только что известили. Ссылки без «#» — легаси-пути вида `/crm/deals`,
    // они по-прежнему ничего не адресуют, поэтому обрабатываются старым способом.
    const link = n.link || '';
    if (link.startsWith('#')) return { hash: link.slice(1) };
    if (n.deal) {
        return { hash: `${isSeller ? 'deal-quote' : 'request-detail'}/${n.deal}` };
    }
    if (link.toLowerCase().includes('profile')) return { page: 'profile' };
    return { page: isSeller ? 'crm-deals' : 'my-requests' };
}

export const NotificationCenter: React.FC<NotificationCenterProps> = ({ onNavigate }) => {
    const { t, i18n } = useTranslation();
    const activeStatus = useUserStore((s) => s.activeStatus);
    const accessToken = useAuthStore((s) => s.accessToken);
    const [isOpen, setIsOpen] = useState(false);
    const [notifications, setNotifications] = useState<Notification[]>([]);
    const [unreadCount, setUnreadCount] = useState(0);
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [isLoadingMore, setIsLoadingMore] = useState(false);

    const dateLocale = i18n.language === 'ru' ? ru : enUS;

    const fetchNotifications = useCallback(async () => {
        // F2.1 moved the access token to memory (never localStorage), so the old
        // localStorage('"accessToken"') gate ALWAYS failed → notifications never loaded (empty
        // panel, the root of "уведомления не приходят"). Gate on the in-memory token instead.
        if (!getAccessToken()) return;
        if (typeof document !== 'undefined' && document.hidden) return;
        try {
            const { items, hasMore } = await notificationsApi.getNotificationsPage(1);
            setNotifications(items);
            setUnreadCount(items.filter(n => !n.is_read).length);
            setHasMore(hasMore);
            setPage(1);
        } catch {
            // silently fail — backend may not be running
        }
    }, []);

    // «Показать ещё»: панель загружала только первую страницу, а кнопка под списком не делала
    // ничего — до остальной истории было не добраться. Периодическое обновление возвращает
    // список к первой странице намеренно: подгруженный хвост не должен расти бесконечно.
    const loadMore = useCallback(async () => {
        if (isLoadingMore || !hasMore) return;
        setIsLoadingMore(true);
        try {
            const { items, hasMore: more } = await notificationsApi.getNotificationsPage(page + 1);
            setNotifications(prev => {
                const known = new Set(prev.map(n => n.id));
                return [...prev, ...items.filter(n => !known.has(n.id))];
            });
            setHasMore(more);
            setPage(prev => prev + 1);
        } catch {
            // silently fail — the already-loaded page stays usable
        } finally {
            setIsLoadingMore(false);
        }
    }, [page, hasMore, isLoadingMore]);

    useEffect(() => {
        fetchNotifications();
        const interval = setInterval(fetchNotifications, 60_000);
        const onVisibility = () => { if (!document.hidden) fetchNotifications(); };
        document.addEventListener('visibilitychange', onVisibility);
        return () => {
            clearInterval(interval);
            document.removeEventListener('visibilitychange', onVisibility);
        };
        // Re-run once the in-memory access token is set (after initAuth — otherwise the first
        // fetch on mount no-ops before auth is ready), and when the panel is opened.
    }, [fetchNotifications, accessToken, isOpen]);

    // Realtime WebSocket subscription — falls back to the poll above if WS fails.
    const socketRef = useRef<WebSocket | null>(null);
    useEffect(() => {
        if (!accessToken) return;

        let stopped = false;
        let retry = 0;
        const connect = async () => {
            if (stopped) return;
            let url: string;
            try {
                // Fresh single-use ticket per (re)connect — no JWT in the WS URL.
                url = await authedWsUrl('/ws/notifications/');
            } catch {
                // Couldn't mint a ticket — retry later; the 60s poll still covers us.
                if (stopped) return;
                retry = Math.min(retry + 1, 5);
                setTimeout(connect, 1000 * 2 ** retry);
                return;
            }
            if (stopped) return;
            const ws = new WebSocket(url);
            socketRef.current = ws;
            ws.onmessage = (ev) => {
                try {
                    const payload = JSON.parse(ev.data);
                    if (payload?.type === 'notification' && payload.data?.id) {
                        const incoming = payload.data as Notification;
                        setNotifications((prev) => {
                            if (prev.some((n) => n.id === incoming.id)) return prev;
                            return [incoming, ...prev];
                        });
                        setUnreadCount((c) => c + 1);
                    }
                } catch {
                    // malformed — ignore
                }
            };
            ws.onclose = () => {
                if (stopped) return;
                // Exponential backoff up to 30s
                retry = Math.min(retry + 1, 5);
                setTimeout(connect, 1000 * 2 ** retry);
            };
            ws.onerror = () => {
                ws.close();
            };
        };
        connect();
        return () => {
            stopped = true;
            socketRef.current?.close();
            socketRef.current = null;
        };
    }, [accessToken]);

    const handleMarkAsRead = async (id: number) => {
        try {
            await notificationsApi.markAsRead(id);
            setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
            setUnreadCount(prev => Math.max(0, prev - 1));
        } catch { /* silently fail */ }
    };

    const handleMarkAllRead = async () => {
        try {
            await notificationsApi.markAllAsRead();
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
            setUnreadCount(0);
        } catch { /* silently fail */ }
    };

    return (
        <Sheet open={isOpen} onOpenChange={setIsOpen}>
            <SheetTrigger asChild>
                <Button
                    variant="outline"
                    size="icon"
                    aria-label={t('notifications.title')}
                    className="relative"
                >
                    <Bell className="size-4" aria-hidden="true" />
                    {unreadCount > 0 && (
                        <Badge className="absolute -top-1 -right-1 size-4 p-0 text-xs font-bold">
                            {unreadCount > 99 ? '99+' : unreadCount}
                        </Badge>
                    )}
                </Button>
            </SheetTrigger>

            <SheetContent side="right" showCloseButton={false} className="flex flex-col p-0 sm:max-w-sm">
                <SheetHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
                    <div className="flex items-center gap-3">
                        <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
                            <Bell className="size-4 text-primary" aria-hidden="true" />
                        </div>
                        <div>
                            <SheetTitle className="text-sm">
                                {t('notifications.title')}
                            </SheetTitle>
                            <SheetDescription>
                                {unreadCount > 0
                                    ? t('notifications.unread', { count: unreadCount })
                                    : t('notifications.caughtUp')
                                }
                            </SheetDescription>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {unreadCount > 0 && (
                            <Button
                                variant="ghost"
                                size="xs"
                                onClick={handleMarkAllRead}
                                className="text-primary hover:text-primary/80"
                            >
                                <Check className="size-3" />
                                {t('notifications.markAllRead')}
                            </Button>
                        )}
                        <SheetClose asChild>
                            <Button variant="ghost" size="icon-sm" aria-label={t('common.close')}>
                                <span className="sr-only">{t('common.close')}</span>
                                &times;
                            </Button>
                        </SheetClose>
                    </div>
                </SheetHeader>

                <ScrollArea className="flex-1">
                    {notifications.length === 0 ? (
                        <div className="flex flex-col items-center justify-center gap-3 p-8 text-center h-full">
                            <div className="flex size-16 items-center justify-center rounded-2xl bg-muted">
                                <BellOff className="size-7 text-muted-foreground" aria-hidden="true" />
                            </div>
                            <div>
                                <p className="text-sm font-semibold text-foreground">
                                    {t('notifications.empty')}
                                </p>
                                <p className="mt-1 text-xs text-muted-foreground">
                                    {t('notifications.emptyHint')}
                                </p>
                            </div>
                        </div>
                    ) : (
                        <div>
                            {notifications.map((n, index) => {
                                const typeCode = n.type_code ?? 'INFO';
                                const Icon = getTypeIcon(typeCode);
                                return (
                                    <React.Fragment key={n.id}>
                                        <div
                                            role="button"
                                            tabIndex={0}
                                            onClick={() => !n.is_read && handleMarkAsRead(n.id)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' || e.key === ' ') {
                                                    e.preventDefault();
                                                    if (!n.is_read) handleMarkAsRead(n.id);
                                                }
                                            }}
                                            className={cn(
                                                'cursor-pointer px-5 py-4 transition-colors border-l-2',
                                                n.is_read
                                                    ? 'border-transparent opacity-50 hover:opacity-70'
                                                    : 'border-primary bg-primary/8 hover:bg-primary/12'
                                            )}
                                        >
                                            <div className="flex gap-3">
                                                <div className={cn(
                                                    'flex size-8 shrink-0 items-center justify-center rounded-lg border',
                                                    getTypeColor(typeCode, n.is_read)
                                                )}>
                                                    <Icon className="size-4" aria-hidden="true" />
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <p className={cn(
                                                        'truncate text-sm font-semibold leading-tight',
                                                        n.is_read
                                                            ? 'text-muted-foreground'
                                                            : 'text-foreground'
                                                    )}>
                                                        {n.title}
                                                    </p>
                                                    <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
                                                        {n.message}
                                                    </p>
                                                    <div className="mt-2 flex items-center justify-between">
                                                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                                            <Clock className="size-3" aria-hidden="true" />
                                                            {formatDistanceToNow(new Date(n.created_at), { addSuffix: true, locale: dateLocale })}
                                                        </span>
                                                        {(n.link || n.deal) && (
                                                            onNavigate ? (
                                                                <Button
                                                                    variant="link"
                                                                    size="xs"
                                                                    className="h-auto p-0 text-primary hover:text-primary/80"
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        if (!n.is_read) handleMarkAsRead(n.id);
                                                                        const target = notificationTarget(n, activeStatus);
                                                                        if (target.hash) window.location.hash = target.hash;
                                                                        else if (target.page) onNavigate(target.page);
                                                                        setIsOpen(false);
                                                                    }}
                                                                >
                                                                    {t('common.open')}
                                                                    <ExternalLink className="size-3" />
                                                                </Button>
                                                            ) : (
                                                                <Button
                                                                    variant="link"
                                                                    size="xs"
                                                                    asChild
                                                                    className="h-auto p-0 text-primary hover:text-primary/80"
                                                                >
                                                                    <a href={n.link} onClick={e => e.stopPropagation()}>
                                                                        {t('common.open')}
                                                                        <ExternalLink className="size-3" />
                                                                    </a>
                                                                </Button>
                                                            )
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                        {index < notifications.length - 1 && <Separator />}
                                    </React.Fragment>
                                );
                            })}
                        </div>
                    )}
                </ScrollArea>

                {hasMore && (
                    <SheetFooter className="border-t p-4">
                        <Button
                            variant="ghost"
                            size="sm"
                            className="w-full text-xs text-muted-foreground"
                            onClick={loadMore}
                            disabled={isLoadingMore}
                        >
                            {isLoadingMore ? t('common.loading') : t('notifications.loadMore')}
                        </Button>
                    </SheetFooter>
                )}
            </SheetContent>
        </Sheet>
    );
};
