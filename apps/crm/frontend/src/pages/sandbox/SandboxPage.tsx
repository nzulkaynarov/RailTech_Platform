import { Alert, App as AntApp, Button, Collapse, Flex, Input, Select, Tag, Typography } from "antd";
import { useRef, useState } from "react";

import type { SandboxMessageIn, SandboxTurnOut } from "../../api/generated/model";
import { useSandboxReset, useSandboxSend } from "../../api/sandboxQueries";
import { EmptyState } from "../../components/EmptyState";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { type SandboxEntry, whyLines } from "../../domain/sandbox";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import "../../components/ChatThread.css";

type SandboxLanguage = NonNullable<SandboxMessageIn["language"]>;

const LANGUAGES: { value: SandboxLanguage; label: string }[] = [
  { value: "ru", label: "Русский" },
  { value: "uz", label: "Oʻzbekcha" },
  { value: "en", label: "English" },
];

function BotTurn({ turn, language }: { turn: SandboxTurnOut; language: SandboxLanguage }) {
  const replies = turn.replies.length ? turn.replies : [{ text: t.sandbox.noReply, buttons: [] }];
  return (
    <div className="chat-row">
      <div className="chat-bubble chat-bot">
        <Typography.Text type="secondary" className="chat-meta">
          {t.sandbox.bot}
        </Typography.Text>
        {replies.map((reply, index) => (
          <div key={index}>
            <div className="chat-text" lang={language}>
              {reply.text}
            </div>
            {reply.buttons.length ? (
              <Flex wrap gap="small" aria-label={t.sandbox.buttons}>
                {reply.buttons.map((label) => (
                  <Tag key={label} lang={language}>
                    {label}
                  </Tag>
                ))}
              </Flex>
            ) : null}
          </div>
        ))}
        <Collapse
          size="small"
          ghost
          items={[
            {
              key: "why",
              label: t.sandbox.whyTitle,
              children: (
                <ul className="chat-meta">
                  {whyLines(turn.why).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}

function Thread({ entries, language }: { entries: SandboxEntry[]; language: SandboxLanguage }) {
  if (!entries.length) return <EmptyState title={t.sandbox.empty} />;
  return (
    <div className="chat-list" role="log" aria-live="polite">
      {entries.map((entry) =>
        entry.role === "lead" ? (
          <div key={entry.id} className="chat-row chat-own">
            <div className="chat-bubble chat-lead">
              <Typography.Text type="secondary" className="chat-meta">
                {t.sandbox.you}
              </Typography.Text>
              <div className="chat-text" lang={language}>
                {entry.text}
              </div>
            </div>
          </div>
        ) : (
          <BotTurn key={entry.id} turn={entry.turn} language={language} />
        ),
      )}
    </div>
  );
}

export function SandboxPage() {
  const [language, setLanguage] = useState<SandboxLanguage>("ru");
  const [text, setText] = useState("");
  const [entries, setEntries] = useState<SandboxEntry[]>([]);
  const nextId = useRef(0);
  const send = useSandboxSend();
  const reset = useSandboxReset();
  const toastError = useApiErrorToast();
  const { message } = AntApp.useApp();

  const append = (entry: SandboxEntry) => {
    setEntries((list) => [...list, entry]);
  };

  const submit = async (event?: { preventDefault: () => void }) => {
    event?.preventDefault();
    const question = text.trim();
    if (!question || send.isPending) return;
    append({ id: nextId.current++, role: "lead", text: question });
    setText("");
    try {
      const turn = await send.mutateAsync({ text: question, language });
      append({ id: nextId.current++, role: "bot", turn });
    } catch (error) {
      toastError(error);
    }
  };

  const restart = async () => {
    try {
      await reset.mutateAsync();
      setEntries([]);
      void message.success(t.sandbox.resetDone);
    } catch (error) {
      toastError(error);
    }
  };

  return (
    <PageBody>
      <PageHeader
        title={t.page.sandbox}
        extra={
          <Button onClick={() => void restart()} loading={reset.isPending}>
            {t.sandbox.reset}
          </Button>
        }
      />
      <Typography.Paragraph type="secondary">{t.sandbox.intro}</Typography.Paragraph>
      <Alert type="warning" showIcon message={t.sandbox.paid} description={t.sandbox.handoffNote} />
      <Flex gap="small" align="center" wrap>
        <label htmlFor="sandbox-language">{t.sandbox.language}</label>
        <Select
          id="sandbox-language"
          value={language}
          options={LANGUAGES}
          onChange={setLanguage}
          style={{ minWidth: 140 }}
        />
      </Flex>
      <div className="chat-thread">
        <Thread entries={entries} language={language} />
        {send.isPending ? (
          <Typography.Text type="secondary" role="status">
            {t.sandbox.thinking}
          </Typography.Text>
        ) : null}
        <form className="chat-reply" onSubmit={(e) => void submit(e)}>
          <div className="chat-reply-row">
            <Input.TextArea
              aria-label={t.sandbox.placeholder}
              placeholder={t.sandbox.placeholder}
              value={text}
              lang={language}
              autoSize={{ minRows: 1, maxRows: 6 }}
              maxLength={4000}
              onChange={(e) => {
                setText(e.target.value);
              }}
              onPressEnter={(e) => {
                if (!e.shiftKey) void submit(e);
              }}
            />
            <Button type="primary" htmlType="submit" loading={send.isPending}>
              {t.sandbox.send}
            </Button>
          </div>
        </form>
      </div>
    </PageBody>
  );
}
