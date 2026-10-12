import { Button, Grid, Input, Typography } from "antd";
import type { KeyboardEvent } from "react";
import { useEffect, useRef, useState } from "react";

import type { MessageOut } from "../api/generated/model";
import { chatKeyAction, messageLang } from "../domain/chatKeys";
import { t } from "../i18n/ru";
import { formatWhen } from "../lib/time";
import "../styles/workspace.css";
import "./ChatThread.css";
import { EmptyState } from "./EmptyState";

type Props = {
  messages: MessageOut[];
  canReply: boolean;
  hint?: string;
  sending: boolean;
  /** Язык лида — для атрибута `lang` у его сообщений (WCAG 3.1.2). */
  language?: string | undefined;
  onSend: (text: string) => Promise<void>;
};

function Bubble({ message, language }: { message: MessageOut; language: string | undefined }) {
  const own = message.role === "bot" || message.role === "manager";
  const attachments = message.attachments.map((a) =>
    typeof a["name"] === "string" ? a["name"] : "file",
  );
  return (
    <div className={own ? "chat-row chat-own" : "chat-row"}>
      <div className={`chat-bubble chat-${message.role}`}>
        <Typography.Text type="secondary" className="chat-meta">
          {t.roleNames[message.role] ?? message.role} · {formatWhen(message.created_at)}
        </Typography.Text>
        <div className="chat-text" lang={messageLang(message.role, language)}>
          {message.text}
        </div>
        {attachments.length ? (
          <div className="chat-meta">
            <span aria-hidden>📎 </span>
            {t.lead.attachments}: {attachments.join(", ")}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Сенсорный ввод: на телефоне/планшете Enter — перенос строки, отправка кнопкой. */
function useTouchInput(): boolean {
  const screens = Grid.useBreakpoint();
  const coarse = typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;
  return coarse || screens.md === false;
}

type ReplyProps = { sending: boolean; onSend: (text: string) => Promise<void> };

/** Поле ответа: закреплено внизу на телефоне; клавиши — `domain/chatKeys`. */
function ReplyBox({ sending, onSend }: ReplyProps) {
  const [draft, setDraft] = useState("");
  const touch = useTouchInput();
  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    await onSend(text);
    setDraft("");
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const { key, shiftKey, ctrlKey, metaKey } = e;
    const isComposing = e.nativeEvent.isComposing;
    const action = chatKeyAction({ key, shiftKey, ctrlKey, metaKey, isComposing }, touch);
    if (action !== "send") return;
    e.preventDefault();
    void send();
  };
  return (
    <div className="chat-reply">
      <div className="chat-reply-row">
        <Input.TextArea
          value={draft}
          autoSize={{ minRows: 1, maxRows: 5 }}
          aria-label={t.lead.replyLabel}
          placeholder={t.lead.replyPlaceholder}
          onChange={(e) => {
            setDraft(e.target.value);
          }}
          onKeyDown={onKeyDown}
        />
        <Button
          type="primary"
          className="touch-target"
          loading={sending}
          onClick={() => void send()}
        >
          {t.lead.send}
        </Button>
      </div>
      {touch ? null : (
        <Typography.Text type="secondary" className="chat-meta">
          {t.lead.replyKeys}
        </Typography.Text>
      )}
    </div>
  );
}

/** Переписка с лидом и поле ответа (только ответственный в режиме human). */
export function ChatThread({ messages, canReply, hint, sending, language, onSend }: Props) {
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  return (
    <div className="chat-thread">
      <div
        className="chat-list"
        data-testid="chat-thread"
        role="log"
        tabIndex={0}
        aria-label={t.lead.chat}
      >
        {messages.length ? (
          messages.map((m) => <Bubble key={m.id} message={m} language={language} />)
        ) : (
          <EmptyState title={t.lead.chatEmpty} hint={t.lead.chatEmptyHint} />
        )}
        <div ref={bottom} />
      </div>
      {canReply ? (
        <ReplyBox sending={sending} onSend={onSend} />
      ) : (
        <Typography.Text type="secondary">{hint ?? t.lead.replyHint}</Typography.Text>
      )}
    </div>
  );
}
