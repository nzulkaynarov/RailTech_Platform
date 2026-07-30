import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquare } from 'lucide-react';
import { crmApi, type Message } from '@/api/crmApi';
import { useUserStore } from '@/store/userStore';
import { dealsListRoute } from '@/lib/documentRoute';

import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetClose,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';

interface ChatDrawerProps {
  onNavigate: (target: string) => void;
}

export function ChatDrawer({ onNavigate }: ChatDrawerProps) {
  // «К сделке» у продавца — очередь сделок, у покупателя — его заявки (U1).
  const activeStatus = useUserStore((state) => state.activeStatus);
  const viewer = { isSeller: activeStatus === 'SELLER' };
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);

  const fetchMessages = useCallback(async () => {
    try {
      const data = await crmApi.getRecentMessages();
      setMessages(data);
    } catch {
      // silent — backend may not be running
    }
  }, []);

  useEffect(() => {
    if (isOpen) fetchMessages();
  }, [isOpen, fetchMessages]);

  // Deduplicate and group by deal
  const seen = new Set<number>();
  const unique = messages.filter(m => {
    if (seen.has(m.id)) return false;
    seen.add(m.id);
    return true;
  });
  const grouped = new Map<number, Message[]>();
  unique.forEach(m => {
    const list = grouped.get(m.deal) ?? [];
    list.push(m);
    grouped.set(m.deal, list);
  });

  return (
    <Sheet open={isOpen} onOpenChange={setIsOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('chat.title')}
          className="relative"
        >
          <MessageSquare className="size-4" aria-hidden="true" />
        </Button>
      </SheetTrigger>

      <SheetContent side="right" showCloseButton={false} className="flex flex-col p-0 sm:max-w-sm">
        <SheetHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
              <MessageSquare className="size-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <SheetTitle className="text-sm">{t('chat.title')}</SheetTitle>
              <SheetDescription className="text-xs">{t('chat.description')}</SheetDescription>
            </div>
          </div>
          <SheetClose asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t('common.close')}>
              <span className="sr-only">{t('common.close')}</span>
              &times;
            </Button>
          </SheetClose>
        </SheetHeader>

        <ScrollArea className="flex-1">
          {unique.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
              <div className="flex size-16 items-center justify-center rounded-2xl bg-muted">
                <MessageSquare className="size-7 text-muted-foreground" aria-hidden="true" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">{t('chat.noMessages')}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t('chat.noMessagesHint')}</p>
              </div>
            </div>
          ) : (
            <div>
              {Array.from(grouped.entries()).map(([dealId, msgs]) => (
                <div key={dealId} className="border-b last:border-b-0">
                  <button
                    className="flex w-full items-center gap-2 px-5 py-2.5 text-left hover:bg-accent transition-colors"
                    onClick={() => { setIsOpen(false); onNavigate(dealsListRoute(viewer)); }}
                  >
                    <MessageSquare className="size-3.5 text-primary shrink-0" />
                    <span className="text-xs font-semibold text-primary">
                      {t('pages.quotes.dealRef', { id: dealId })}
                    </span>
                    <Badge variant="secondary" className="ml-auto text-xs">{msgs.length}</Badge>
                  </button>
                  <div className="px-5 pb-3 space-y-2">
                    {msgs.slice(0, 3).map(msg => (
                      <div key={msg.id} className="rounded-lg border bg-card p-2.5 space-y-1">
                        <p className="text-sm leading-snug">{msg.text}</p>
                        <div className="flex items-center justify-between">
                          <p className="text-xs text-muted-foreground">{msg.sender_name}</p>
                          <p className="text-xs text-muted-foreground tabular-nums">
                            {new Date(msg.timestamp).toLocaleString()}
                          </p>
                        </div>
                      </div>
                    ))}
                    {msgs.length > 3 && (
                      <p className="text-xs text-muted-foreground text-center">
                        +{msgs.length - 3} {t('chat.moreMessages')}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
