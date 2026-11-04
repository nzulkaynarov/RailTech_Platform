import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Eye, MessagesSquare, Paperclip, Send, Tag, UserRound, X } from 'lucide-react';

import type { MessageContext, PortalMessage } from '@/api/portal';
import { botLink } from '@/app/links';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { TelegramLinkButton } from '@/components/TelegramLinkButton';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useMessagesFeed } from '@/hooks/useMessagesFeed';
import { formatDateTime } from '@/lib/format';
import {
  MESSAGE_MAX_LENGTH,
  contextFromSearch,
  contextHref,
  contextModule,
  responderName,
  type PendingMessage,
} from '@/lib/messages';
import { cn } from '@/lib/utils';
import { useAppMode } from '@/session/mode';
import { useCanAct, useHasModule, useMe } from '@/session/useMe';

/**
 * «Сообщения» (CHAT-1, ADR-0023): одна лента на компанию — её видят все контакты компании, менеджер отвечает из очереди
 * «Сообщения» Платформы. Обновление — опрос, пока экран открыт (`useMessagesFeed`). «Написать менеджеру» со страницы
 * документа приходит сюда с меткой (`?about=quote&id=…&number=…`): плашка над полем, метка уходит с сообщением.
 * Текст — только как текст (без HTML), переносы строк сохраняются.
 */
export function MessagesPage() {
  const { t } = useTranslation();
  const me = useMe().data;
  const { feed, messages, pending, submit, retry } = useMessagesFeed({ initialUnread: me?.unread ?? 0 });
  const bot = botLink();

  return (
    <>
      <PageHeader
        title={t('pages.messages.title')}
        subtitle={t('pages.messages.subtitle')}
        icon={MessagesSquare}
        actions={
          bot ? (
            <TelegramLinkButton href={bot} variant="ghost" size="sm">
              {t('pages.messages.telegram')}
            </TelegramLinkButton>
          ) : null
        }
      />
      <div className="flex flex-col gap-4">
        <ChatInfo responder={responderName(messages)} />
        {feed.isPending ? (
          <ListSkeleton rows={3} />
        ) : feed.isError ? (
          <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
        ) : (
          <Feed messages={messages} pending={pending} onRetry={retry} />
        )}
        <Composer onSend={submit} />
      </div>
    </>
  );
}

/**
 * Шапка чата: кто отвечает (имя менеджера из последнего ответа, иначе — команда) и кто видит переписку. Срок ответа не
 * обещаем: рабочего времени CRM у портала нет (хвост PR).
 */
function ChatInfo({ responder }: { responder: string | null }) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t('pages.messages.infoLabel')}
      className="flex flex-col gap-1.5 rounded-xl border border-border/60 bg-background px-3 py-2 text-sm"
    >
      <p className="flex items-center gap-2">
        <UserRound className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        {responder ? t('pages.messages.responder', { name: responder }) : t('pages.messages.responderTeam')}
      </p>
      <p className="flex items-center gap-2 text-muted-foreground">
        <Eye className="size-4 shrink-0" aria-hidden="true" />
        {t('pages.messages.visibleToCompany')}
      </p>
    </section>
  );
}

function Feed({
  messages,
  pending,
  onRetry,
}: {
  messages: PortalMessage[];
  pending: PendingMessage[];
  onRetry: (item: PendingMessage) => void;
}) {
  const { t } = useTranslation();
  const listRef = useRef<HTMLOListElement>(null);
  const last = messages.length + pending.length;
  // Новое сообщение — лента прокручивается к нему (своё отправленное и ответ менеджера при опросе)
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [last]);

  if (messages.length === 0 && pending.length === 0) {
    return (
      <EmptyState icon={MessagesSquare} title={t('pages.messages.emptyTitle')} text={t('pages.messages.emptyText')} />
    );
  }
  return (
    <ol
      ref={listRef}
      aria-label={t('pages.messages.feed')}
      aria-live="polite"
      className="flex max-h-[60dvh] flex-col gap-3 overflow-y-auto rounded-2xl border border-border/60 bg-muted/40 p-3 md:p-4"
    >
      {messages.map((message) => (
        <Bubble
          key={message.id}
          mine={message.mine}
          author={authorOf(message, t)}
          time={message.created_at}
          text={message.text}
          context={message.context}
        />
      ))}
      {pending.map((item) => (
        <Bubble key={item.clientMessageId} mine author={t('pages.messages.you')} text={item.text} context={item.context}>
          {item.status === 'sending' ? (
            <span className="text-xs text-muted-foreground">{t('pages.messages.sending')}</span>
          ) : (
            <span className="flex items-center gap-2 text-xs text-destructive">
              {t('pages.messages.failed')}
              <Button variant="outline" size="sm" onClick={() => onRetry(item)}>
                {t('common.retry')}
              </Button>
            </span>
          )}
        </Bubble>
      ))}
    </ol>
  );
}

function authorOf(message: PortalMessage, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (message.mine) return t('pages.messages.you');
  if (message.direction === 'manager') {
    return message.author_name
      ? t('pages.messages.managerNamed', { name: message.author_name })
      : t('pages.messages.manager');
  }
  return message.author_name ?? t('pages.messages.colleague');
}

function Bubble({
  mine,
  author,
  time,
  text,
  context,
  children,
}: {
  mine: boolean;
  author: string;
  time?: string;
  text: string;
  context: MessageContext | null;
  children?: ReactNode;
}) {
  const { i18n } = useTranslation();
  return (
    <li className={cn('flex max-w-[85%] flex-col gap-1', mine ? 'items-end self-end' : 'items-start self-start')}>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{author}</span>
        {time ? (
          <>
            {' · '}
            <time dateTime={time}>{formatDateTime(time, i18n.language)}</time>
          </>
        ) : null}
      </p>
      {context ? <ContextLabel context={context} /> : null}
      <p
        className={cn(
          'rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap',
          mine ? 'bg-primary text-primary-foreground' : 'border border-border bg-background text-foreground',
        )}
      >
        {text}
      </p>
      {children}
    </li>
  );
}

/** Метка документа: ссылка на документ в кабинете, если его раздел открыт сессии; иначе — просто подпись. */
function ContextLabel({ context }: { context: MessageContext }) {
  const { t } = useTranslation();
  const open = useHasModule(contextModule(context.kind));
  const label = t(`pages.messages.context.${context.kind}`, { number: context.number });
  const base = 'inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-0.5 text-xs';
  if (!open) {
    return (
      <span className={cn(base, 'text-muted-foreground')}>
        <Tag className="size-3" aria-hidden="true" />
        {label}
      </span>
    );
  }
  return (
    <Link
      to={contextHref(context)}
      className={cn(base, 'text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring')}
    >
      <Tag className="size-3" aria-hidden="true" />
      {label}
    </Link>
  );
}

/** Вложений в чате пока нет: подсказка, что файл прикладывают к запросу (ссылка — если раздел запросов открыт). */
function AttachHint() {
  const { t } = useTranslation();
  const requests = useHasModule('catalog_requests');
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <Paperclip className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span>
        {t('pages.messages.attachHint')}
        {requests ? (
          <>
            {' '}
            <Link to="/requests" className="text-primary underline underline-offset-2">
              {t('pages.messages.attachLink')}
            </Link>
          </>
        ) : null}
      </span>
    </p>
  );
}

function Composer({ onSend }: { onSend: (text: string, context: MessageContext | null) => void }) {
  const { t } = useTranslation();
  const mode = useAppMode();
  const canAct = useCanAct();
  const fieldId = useId();
  const hintId = useId();
  const [params, setParams] = useSearchParams();
  const context = contextFromSearch(params);
  const [text, setText] = useState('');
  const body = text.trim();

  const clearContext = () =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const key of ['about', 'id', 'number']) next.delete(key);
        return next;
      },
      { replace: true },
    );

  const send = () => {
    if (!body || !canAct) return;
    onSend(body, context);
    setText('');
    if (context) clearContext();
  };

  // Enter — отправить, Shift+Enter — новая строка; в Mini App (экранная клавиатура) отправляет только кнопка
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (mode !== 'web' || event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send();
  };

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      {context ? (
        <div
          role="group"
          aria-label={t('pages.messages.aboutLabel')}
          className="flex items-center justify-between gap-2 rounded-xl border border-border bg-accent/60 px-3 py-2 text-sm text-primary"
        >
          <span className="flex min-w-0 items-center gap-2">
            <Tag className="size-4 shrink-0" aria-hidden="true" />
            <span className="truncate">
              {t('pages.messages.about', {
                what: t(`pages.messages.context.${context.kind}`, { number: context.number }),
              })}
            </span>
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={clearContext}
            aria-label={t('pages.messages.removeAbout')}
            title={t('pages.messages.removeAbout')}
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      ) : null}
      <Label htmlFor={fieldId}>{t('pages.messages.field')}</Label>
      <Textarea
        id={fieldId}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        maxLength={MESSAGE_MAX_LENGTH}
        rows={3}
        disabled={!canAct}
        placeholder={t('pages.messages.placeholder')}
        aria-describedby={hintId}
      />
      <AttachHint />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p id={hintId} className="text-xs text-muted-foreground">
          {canAct ? t(mode === 'web' ? 'pages.messages.hintWeb' : 'pages.messages.hint') : t('pages.messages.viewOnly')}
        </p>
        <Button type="submit" disabled={!canAct || !body}>
          <Send aria-hidden="true" />
          {t('pages.messages.send')}
        </Button>
      </div>
    </form>
  );
}
