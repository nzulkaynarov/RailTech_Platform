import { useState, useEffect, useRef } from 'react';
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
  Paperclip,
  Clock,
  User,
  CheckCheck,
  Info,
} from 'lucide-react';

interface ChatMessage {
  id: number;
  sender: 'manager' | 'client' | 'system';
  name?: string;
  textKey?: string;
  text?: string;
  time?: string;
}

const initialMessages: ChatMessage[] = [];

const delayedMessages: { delay: number; message: ChatMessage }[] = [];

interface DemoDocument {
  nameKey: string;
  name: string;
  size: string;
  date: string;
}

const documents: DemoDocument[] = [];

export function DealChatPanel(): React.ReactNode {
  // TODO: when implementing live chat fetching, accept dealId prop
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [inputValue, setInputValue] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  // TODO: Fetch messages from crmApi.getMessages(dealId) when dealId changes
  // useEffect(() => {
  //   if (dealId) {
  //     crmApi.getMessages(dealId).then(setMessages);
  //   }
  // }, [dealId]);

  useEffect(() => {
    const timers = delayedMessages.map(({ delay, message }) =>
      setTimeout(() => {
        setMessages((prev) => [...prev, message]);
      }, delay),
    );

    return () => {
      timers.forEach(clearTimeout);
    };
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

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
                        'max-w-[85%] rounded-lg px-2.5 py-1.5 text-xs leading-relaxed',
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
            <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0">
              <Paperclip className="h-3.5 w-3.5" />
            </Button>
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
            <div className="flex flex-col gap-1">
              {documents.map((doc) => {
                const isPdf = doc.name.endsWith('.pdf');
                return (
                  <div
                    key={doc.name}
                    className="hover:bg-muted/50 flex items-center gap-2.5 rounded-md px-2 py-2 transition-colors"
                  >
                    <div
                      className={cn(
                        'flex h-8 w-8 shrink-0 items-center justify-center rounded',
                        isPdf ? 'bg-muted text-muted-foreground' : 'bg-muted text-muted-foreground',
                      )}
                    >
                      <FileText className="h-4 w-4" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium">{doc.name}</p>
                      <div className="text-muted-foreground flex items-center gap-2 text-xs">
                        <span>{doc.size}</span>
                        <span className="text-muted-foreground/40">|</span>
                        <span className="flex items-center gap-0.5">
                          <Clock className="h-2.5 w-2.5" />
                          {doc.date}
                        </span>
                      </div>
                    </div>

                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0">
                      <FileText className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </Card>
  );
}
