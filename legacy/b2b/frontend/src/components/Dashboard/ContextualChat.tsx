import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { crmApi, Message } from '../../api/crmApi';
import { Send, User, Bot, Loader2, Wifi, WifiOff } from 'lucide-react';
import { clsx } from 'clsx';
import { useAuthStore } from '../../store/authStore';
import { Button } from '@/components/ui/button';

interface ContextualChatProps {
    dealId: number;
}

export const ContextualChat: React.FC<ContextualChatProps> = ({ dealId }) => {
    const { t } = useTranslation();
    const [messages, setMessages] = useState<Message[]>([]);
    const [newMessage, setNewMessage] = useState('');
    const [isLoading, setIsLoading] = useState(true);
    const [isConnected, setIsConnected] = useState(false);
    const socketRef = useRef<WebSocket | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const { accessToken, user } = useAuthStore();

    useEffect(() => {
        const fetchInitialMessages = async () => {
            try {
                const data = await crmApi.getMessages(dealId);
                setMessages(data);
            } catch (error) {
                console.error('Failed to fetch messages:', error);
            } finally {
                setIsLoading(false);
            }
        };

        fetchInitialMessages();

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsHost = import.meta.env.VITE_WS_URL || `${wsProtocol}//${window.location.host}`;
        const wsUrl = `${wsHost}/ws/chat/${dealId}/?token=${encodeURIComponent(accessToken || '')}`;

        const socket = new WebSocket(wsUrl);
        socketRef.current = socket;

        socket.onopen = () => {
            setIsConnected(true);
        };

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            // Handle auth rejection
            if (data.error) {
                console.error('WebSocket error:', data.error);
                return;
            }
            if (data.message) {
                const incomingMsg = data.message;
                setMessages((prev) => {
                    if (prev.some(m => m.id === incomingMsg.id)) return prev;
                    return [...prev, {
                        ...incomingMsg,
                        is_me: incomingMsg.sender === user?.id
                    }];
                });
            }
        };

        socket.onclose = () => {
            setIsConnected(false);
        };

        return () => {
            socket.close();
        };
    }, [dealId, accessToken, user?.id]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages]);

    const handleSend = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newMessage.trim() || !socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;

        socketRef.current.send(JSON.stringify({
            text: newMessage
        }));
        setNewMessage('');
    };

    if (isLoading) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <Loader2 className="w-6 h-6 animate-spin text-primary" aria-hidden="true" />
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full bg-background transition-colors">
            {/* Status bar */}
            <div className="px-4 py-1.5 flex items-center justify-end gap-2 border-b border-border bg-muted dark:bg-background">
                <span className="text-xs text-muted-foreground">
                    {isConnected ? t('chat.connected') : t('chat.connectionLost')}
                </span>
                {isConnected ? (
                    <Wifi className="w-3 h-3 text-success" aria-label={t('chat.connected')} />
                ) : (
                    <WifiOff className="w-3 h-3 text-destructive" aria-label={t('chat.connectionLost')} />
                )}
            </div>

            {/* Messages area */}
            <div
                ref={scrollRef}
                className="flex-1 p-4 overflow-y-auto flex flex-col gap-3 custom-scrollbar"
                role="log"
                aria-label={t('chat.title')}
            >
                {messages.length === 0 && (
                    <div className="text-center text-muted-foreground text-sm mt-10">
                        {t('chat.emptyState')}
                    </div>
                )}
                {messages.map((msg) => (
                    <div
                        key={msg.id}
                        className={clsx(
                            'flex flex-col max-w-prose',
                            msg.is_me ? 'self-end' : 'self-start'
                        )}
                    >
                        <div className={clsx(
                            'flex items-center gap-2 mb-1',
                            msg.is_me ? 'justify-end' : 'justify-start'
                        )}>
                            {!msg.is_me && <Bot className="w-3 h-3 text-primary" aria-hidden="true" />}
                            <span className="text-xs text-muted-foreground">
                                {msg.sender_name || (msg.is_me ? t('chat.title') : t('nav.profile'))}
                            </span>
                            {msg.is_me && <User className="w-3 h-3 text-muted-foreground" aria-hidden="true" />}
                        </div>
                        <div className={clsx(
                            'p-3 rounded-xl text-sm leading-relaxed shadow-sm',
                            msg.is_me
                                ? 'bg-primary text-primary-foreground rounded-tr-sm'
                                : 'bg-muted text-foreground border border-border rounded-tl-sm'
                        )}>
                            {msg.text}
                            <span className={clsx(
                                'text-xs mt-1 block',
                                msg.is_me ? 'text-primary-foreground/70' : 'text-muted-foreground'
                            )}>
                                {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                        </div>
                    </div>
                ))}
            </div>

            {/* Input area */}
            <form
                onSubmit={handleSend}
                className="p-3 border-t border-border bg-background"
            >
                <div className="relative flex items-center">
                    <input
                        type="text"
                        value={newMessage}
                        onChange={(e) => setNewMessage(e.target.value)}
                        placeholder={isConnected ? t('chat.placeholder') : t('chat.connectionLost')}
                        disabled={!isConnected}
                        aria-label={t('chat.placeholder')}
                        className="w-full pl-4 pr-12 py-2.5 bg-muted border border-border rounded-xl text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <Button
                        type="submit"
                        size="icon"
                        disabled={!newMessage.trim() || !isConnected}
                        aria-label={t('chat.send')}
                        className={clsx(
                            'absolute right-1.5 p-2 h-auto w-auto rounded-lg transition-all',
                            newMessage.trim() && isConnected
                                ? 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm'
                                : 'bg-muted text-muted-foreground'
                        )}
                    >
                        <Send className="w-4 h-4" />
                    </Button>
                </div>
            </form>
        </div>
    );
};
