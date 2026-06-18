import { useState, useRef, useEffect, useCallback, FormEvent } from 'react';
import { wsBase } from '@/lib/ws';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import {
  MessageSquare,
  FileText,
  Send,
  User as UserIcon,
  Info,
  Wifi,
  WifiOff,
  Loader2,
} from 'lucide-react';
import { DealAttachmentsPanel } from './DealAttachmentsPanel';
import { crmApi, Message } from '@/api/crmApi';
import { useAuthStore } from '@/store/authStore';

interface DealChatPanelProps {
  dealId?: number | null;
}

function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

export function DealChatPanel({ dealId }: DealChatPanelProps = {}): React.ReactNode {
  const { t } = useTranslation();
  const accessToken = useAuthStore((s) => s.accessToken);
  const currentUserId = useAuthStore((s) => s.user?.id);

  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isSending, setIsSending] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const appendMessage = useCallback((incoming: Message) => {
    setMessages((prev) => {
      if (prev.some((m) => m.id === incoming.id)) return prev;
      return [...prev, incoming];
    });
  }, []);

  useEffect(() => {
    if (!dealId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    crmApi
      .getMessages(dealId)
      .then((data) => {
        if (cancelled) return;
        setMessages(data);
      })
      .catch(() => {
        if (cancelled) return;
        toast.error(t('dealChat.loadError'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dealId, t]);

  useEffect(() => {
    if (!dealId || !accessToken) {
      setIsConnected(false);
      return;
    }
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const connect = () => {
      if (cancelled) return;
      const wsUrl = `${wsBase()}/ws/chat/${dealId}/?token=${encodeURIComponent(accessToken)}`;
      const socket = new WebSocket(wsUrl);
      socketRef.current = socket;

      socket.onopen = () => {
        if (cancelled) return;
        attempt = 0; // reset backoff once a connection actually succeeds
        setIsConnected(true);
      };
      // The status text already promises reconnection — actually do it. A flaky
      // network or a server blip now recovers on its own (exponential backoff,
      // capped) instead of staying "disconnected" until a full page reload.
      const scheduleReconnect = () => {
        if (cancelled) return;
        setIsConnected(false);
        const delay = Math.min(15000, 1000 * 2 ** attempt);
        attempt += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
      socket.onclose = scheduleReconnect;
      socket.onerror = () => { socket.close(); };
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data?.error) return;
          if (typeof data?.id === 'number' && typeof data?.text === 'string') {
            appendMessage({
              id: data.id,
              deal: data.deal ?? dealId,
              sender: data.sender,
              sender_name: data.sender_name ?? '',
              text: data.text,
              message_type: data.message_type ?? 'CHAT',
              timestamp: data.timestamp,
              is_me: currentUserId ? data.sender === currentUserId : false,
            });
          }
        } catch {
          // ignore malformed frames
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [dealId, accessToken, currentUserId, appendMessage]);

  useEffect(() => {
    const container = scrollContainerRef.current?.querySelector(
      '[data-radix-scroll-area-viewport]',
    ) as HTMLElement | null;
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [messages]);

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text || !dealId || isSending) return;
    setIsSending(true);
    try {
      const created = await crmApi.sendMessage(dealId, text);
      appendMessage({ ...created, is_me: true });
      setInputValue('');
    } catch {
      toast.error(t('dealChat.sendError'));
    } finally {
      setIsSending(false);
    }
  }

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <Tabs defaultValue="chat" className="flex h-full flex-col">
        <div className="border-b px-3 py-2">
          <TabsList className="w-full">
            <TabsTrigger value="chat" className="flex-1 gap-1.5 text-xs">
              <MessageSquare className="h-3.5 w-3.5" />
              {t('dealChat.tabs.chat')}
            </TabsTrigger>
            <TabsTrigger value="documents" className="flex-1 gap-1.5 text-xs">
              <FileText className="h-3.5 w-3.5" />
              {t('dealChat.tabs.documents')}
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="chat" className="mt-0 flex flex-1 flex-col overflow-hidden">
          <div className="flex items-center justify-end gap-1.5 border-b px-3 py-1.5">
            {isConnected ? (
              <>
                <Wifi className="h-3 w-3 text-success" aria-hidden="true" />
                <span className="text-xs text-muted-foreground">
                  {t('chat.connected')}
                </span>
              </>
            ) : (
              <>
                <WifiOff className="h-3 w-3 text-destructive" aria-hidden="true" />
                <span className="text-xs text-muted-foreground">
                  {t('chat.connectionLost')}
                </span>
              </>
            )}
          </div>

          <ScrollArea className="flex-1 px-3 py-2" ref={scrollContainerRef}>
            <div className="flex flex-col gap-2">
              {!dealId ? (
                <div className="flex justify-center py-8">
                  <p className="text-xs text-muted-foreground">
                    {t('dealAttachments.noDeal')}
                  </p>
                </div>
              ) : isLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />
                </div>
              ) : messages.length === 0 ? (
                <div className="flex justify-center py-8">
                  <p className="text-xs text-muted-foreground">{t('chat.emptyState')}</p>
                </div>
              ) : (
                messages.map((msg) => {
                  if (msg.message_type === 'SYSTEM' || msg.message_type === 'NOTIFICATION') {
                    return (
                      <div key={msg.id} className="flex justify-center py-1">
                        <Badge
                          variant="secondary"
                          className="text-muted-foreground text-xs font-normal gap-1"
                        >
                          <Info className="h-3 w-3" />
                          {msg.text}
                        </Badge>
                      </div>
                    );
                  }
                  const isMe = msg.is_me;
                  return (
                    <div
                      key={msg.id}
                      className={cn(
                        'flex flex-col gap-0.5',
                        isMe ? 'items-end' : 'items-start',
                      )}
                    >
                      <div className="flex items-center gap-1 px-1">
                        <UserIcon className="text-muted-foreground h-3 w-3" />
                        <span className="text-muted-foreground text-xs font-medium">
                          {msg.sender_name || t('nav.profile')}
                        </span>
                      </div>
                      <div
                        className={cn(
                          'max-w-prose rounded-lg px-2.5 py-1.5 text-xs leading-relaxed whitespace-pre-wrap break-words',
                          isMe
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted text-foreground',
                        )}
                      >
                        {msg.text}
                      </div>
                      <div
                        className={cn(
                          'flex items-center gap-1 px-1',
                          isMe ? 'flex-row-reverse' : 'flex-row',
                        )}
                      >
                        <span className="text-muted-foreground text-xs">
                          {formatTime(msg.timestamp)}
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </ScrollArea>

          <Separator />

          <form onSubmit={handleSend} className="flex items-center gap-1.5 p-2">
            <Input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={t('dealChat.placeholder')}
              className="h-7 text-xs"
              disabled={!dealId || isSending}
              maxLength={5000}
            />
            <Button
              type="submit"
              size="icon"
              className="h-7 w-7 shrink-0"
              disabled={!dealId || isSending || inputValue.trim().length === 0}
              aria-label={t('chat.send')}
            >
              {isSending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
            </Button>
          </form>
        </TabsContent>

        <TabsContent value="documents" className="mt-0 flex-1 overflow-hidden">
          <ScrollArea className="h-full px-3 py-2">
            {dealId ? (
              <DealAttachmentsPanel dealId={dealId} />
            ) : (
              <p className="text-xs text-muted-foreground">{t('dealAttachments.noDeal')}</p>
            )}
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </Card>
  );
}
