import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Bell, Info, AlertTriangle, CheckCircle, Clock, Check, ExternalLink, BellOff } from 'lucide-react';
import { notificationsApi, Notification } from '@/api/notificationsApi';
import { formatDistanceToNow } from 'date-fns';
import { ru, enUS } from 'date-fns/locale';
import { cn } from '@/lib/utils';

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
}

export const NotificationCenter: React.FC<NotificationCenterProps> = () => {
    const { t, i18n } = useTranslation();
    const [isOpen, setIsOpen] = useState(false);
    const [notifications, setNotifications] = useState<Notification[]>([]);
    const [unreadCount, setUnreadCount] = useState(0);

    const dateLocale = i18n.language === 'ru' ? ru : enUS;

    const fetchNotifications = useCallback(async () => {
        try {
            const data = await notificationsApi.getNotifications();
            setNotifications(data);
            setUnreadCount(data.filter(n => !n.is_read).length);
        } catch {
            // silently fail — backend may not be running
        }
    }, []);

    useEffect(() => {
        fetchNotifications();
        const interval = setInterval(fetchNotifications, 30_000);
        return () => clearInterval(interval);
    }, [fetchNotifications]);

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
                            {unreadCount > 9 ? '9+' : unreadCount}
                        </Badge>
                    )}
                </Button>
            </SheetTrigger>

            <SheetContent side="right" showCloseButton={false} className="flex flex-col p-0 sm:max-w-[380px]">
                <SheetHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
                    <div className="flex items-center gap-3">
                        <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
                            <Bell className="size-4 text-primary" aria-hidden="true" />
                        </div>
                        <div>
                            <SheetTitle className="text-sm">
                                {t('notifications.title')}
                            </SheetTitle>
                            <SheetDescription className={cn(unreadCount > 0 ? '' : 'sr-only')}>
                                {unreadCount > 0
                                    ? t('notifications.unread', { count: unreadCount })
                                    : t('notifications.title')
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
                                                    ? 'border-transparent opacity-60 hover:opacity-80'
                                                    : 'border-primary bg-primary/[0.02] hover:bg-primary/5'
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
                                                        {n.link && (
                                                            <Button
                                                                variant="link"
                                                                size="xs"
                                                                asChild
                                                                className="h-auto p-0 text-primary hover:text-primary/80"
                                                            >
                                                                <a
                                                                    href={n.link}
                                                                    onClick={e => e.stopPropagation()}
                                                                >
                                                                    {t('common.open')}
                                                                    <ExternalLink className="size-3" />
                                                                </a>
                                                            </Button>
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

                <SheetFooter className="border-t p-4">
                    <Button variant="ghost" size="sm" className="w-full text-xs text-muted-foreground">
                        {t('notifications.viewAll')}
                    </Button>
                </SheetFooter>
            </SheetContent>
        </Sheet>
    );
};
