import { Button, Empty, Input, Space, Typography } from "antd";
import { useEffect, useRef, useState } from "react";

import type { MessageOut } from "../api/generated/model";
import { t } from "../i18n/ru";
import "./ChatThread.css";
import { formatWhen } from "../lib/time";

type Props = {
  messages: MessageOut[];
  canReply: boolean;
  sending: boolean;
  onSend: (text: string) => Promise<void>;
};

function Bubble({ message }: { message: MessageOut }) {
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
        <div className="chat-text">{message.text}</div>
        {attachments.length ? <div className="chat-meta">📎 {attachments.join(", ")}</div> : null}
      </div>
    </div>
  );
}

/** Переписка с лидом и поле ответа (только владелец лида в режиме human). */
export function ChatThread({ messages, canReply, sending, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    await onSend(text);
    setDraft("");
  };

  return (
    <div className="chat-thread">
      <div className="chat-list" data-testid="chat-thread">
        {messages.length ? messages.map((m) => <Bubble key={m.id} message={m} />) : <Empty />}
        <div ref={bottom} />
      </div>
      {canReply ? (
        <Space.Compact className="chat-reply">
          <Input.TextArea
            value={draft}
            autoSize={{ minRows: 1, maxRows: 5 }}
            placeholder={t.lead.replyPlaceholder}
            onChange={(e) => {
              setDraft(e.target.value);
            }}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <Button type="primary" loading={sending} onClick={() => void send()}>
            {t.lead.send}
          </Button>
        </Space.Compact>
      ) : (
        <Typography.Text type="secondary">{t.lead.replyHint}</Typography.Text>
      )}
    </div>
  );
}
