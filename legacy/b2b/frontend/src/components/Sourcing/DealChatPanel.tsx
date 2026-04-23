import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
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
  User,
  CheckCheck,
  Info,
} from 'lucide-react';
import { DealAttachmentsPanel } from './DealAttachmentsPanel';

interface ChatMessage {
  id: number;
  sender: 'manager' | 'client' | 'system';
  name?: string;
  textKey?: string;
  text?: string;
  time?: string;
}

const initialMessages: ChatMessage[] = [];

export function DealChatPanel({ dealId }: { dealId?: number | null } = {}): React.ReactNode {
  const { t } = useTranslation();
  const [messages] = useState<ChatMessage[]>(initialMessages);
  const [inputValue, setInputValue] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  function getMessageText(msg: ChatMessage): string {
    if (msg.textKey) return t(msg.textKey);
    return msg.text ?? '';
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
          <ScrollArea className="flex-1 px-3 py-2" ref={scrollRef}>
            <div className="flex flex-col gap-2">
              {messages.map((msg) => {
                if (msg.sender === 'system') {
                  return (
                    <div key={msg.id} className="flex justify-center py-1">
                      <Badge
                        variant="secondary"
                        className="text-muted-foreground text-xs font-normal gap-1"
                      >
                        <Info className="h-3 w-3" />
                        {getMessageText(msg)}
                      </Badge>
                    </div>
                  );
                }

                const isManager = msg.sender === 'manager';

                return (
                  <div
                    key={msg.id}
                    className={cn('flex flex-col gap-0.5', isManager ? 'items-end' : 'items-start')}
                  >
                    <div className="flex items-center gap-1 px-1">
                      <User className="text-muted-foreground h-3 w-3" />
                      <span className="text-muted-foreground text-xs font-medium">
                        {msg.name}
                      </span>
                    </div>
                    <div
                      className={cn(
                        'max-w-prose rounded-lg px-2.5 py-1.5 text-xs leading-relaxed',
                        isManager
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted text-foreground',
                      )}
                    >
                      {getMessageText(msg)}
                    </div>
                    <div
                      className={cn(
                        'flex items-center gap-1 px-1',
                        isManager ? 'flex-row-reverse' : 'flex-row',
                      )}
                    >
                      <span className="text-muted-foreground text-xs">{msg.time}</span>
                      {isManager && <CheckCheck className="text-muted-foreground h-3 w-3" />}
                    </div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>

          <Separator />

          <div className="flex items-center gap-1.5 p-2">
            <Input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={t('dealChat.placeholder')}
              className="h-7 text-xs"
            />
            <Button size="icon" className="h-7 w-7 shrink-0">
              <Send className="h-3.5 w-3.5" />
            </Button>
          </div>
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
