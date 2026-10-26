import { Alert, Button, Card, Input, Select } from "antd";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Language, SandboxTurn } from "../../../shared/api/generated/model";
import { useResetSandbox, useSendSandboxMessage } from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { ActionToggle, ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { kbErrorText } from "./errors";

const LANGUAGES: readonly Language[] = ["ru", "uz", "en"];

type Entry =
  { id: number; role: "lead"; text: string } | { id: number; role: "bot"; turn: SandboxTurn };

function Why({ turn }: { turn: SandboxTurn }) {
  const { t } = useTranslation("kb");
  const why = turn.why;
  const decision = t(`sandbox.decisions.${why.decision}`, { defaultValue: why.decision });
  return (
    <details className="pf-kb-why">
      <summary>{t("sandbox.why.title")}</summary>
      <dl className="pf-kb-why-list">
        <dt>{t("sandbox.why.decision")}</dt>
        <dd>{decision}</dd>
        {why.reason ? (
          <>
            <dt>{t("sandbox.why.reason")}</dt>
            <dd>{why.reason}</dd>
          </>
        ) : null}
        {why.best_score !== null ? (
          <>
            <dt>{t("sandbox.why.score")}</dt>
            <dd>{why.best_score.toFixed(2)}</dd>
          </>
        ) : null}
        <dt>{t("sandbox.why.documents")}</dt>
        <dd>{why.documents.length ? why.documents.join(", ") : t("sandbox.why.none")}</dd>
        {why.triggers.length ? (
          <>
            <dt>{t("sandbox.why.triggers")}</dt>
            <dd>
              {why.triggers.map((code) => t(`triggers.${code}`, { defaultValue: code })).join(", ")}
            </dd>
          </>
        ) : null}
        {why.priority ? (
          <>
            <dt>{t("sandbox.why.priority")}</dt>
            <dd>{why.priority}</dd>
          </>
        ) : null}
      </dl>
    </details>
  );
}

function Thread({ entries, language }: { entries: readonly Entry[]; language: Language }) {
  const { t } = useTranslation("kb");
  if (entries.length === 0) return <p className="pf-hint pf-kb-chat-empty">{t("sandbox.empty")}</p>;
  return (
    <div className="pf-kb-chat" role="log" aria-live="polite" aria-label={t("sandbox.log")}>
      {entries.map((entry) =>
        entry.role === "lead" ? (
          <article key={entry.id} className="pf-kb-msg pf-kb-msg--lead">
            <p className="pf-kb-msg-who">{t("sandbox.you")}</p>
            <p className="pf-kb-msg-text" lang={language}>
              {entry.text}
            </p>
          </article>
        ) : (
          <article key={entry.id} className="pf-kb-msg pf-kb-msg--bot">
            <p className="pf-kb-msg-who">{t("sandbox.bot")}</p>
            {entry.turn.replies.length === 0 ? (
              <p className="pf-kb-msg-text">{t("sandbox.noReply")}</p>
            ) : (
              entry.turn.replies.map((reply, index) => (
                <div key={index}>
                  <p className="pf-kb-msg-text" lang={language}>
                    {reply.text}
                  </p>
                  {reply.buttons.length ? (
                    <ul className="pf-kb-buttons" aria-label={t("sandbox.buttons")}>
                      {reply.buttons.map((label) => (
                        <li key={label} lang={language}>
                          {label}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))
            )}
            <Why turn={entry.turn} />
          </article>
        ),
      )}
    </div>
  );
}

/** «Проверить бота»: диалог с ботом как клиент, тот же ход, что в Telegram; платно, в CRM ничего не создаёт. */
export function SandboxView() {
  const { t, i18n } = useTranslation("kb");
  const [language, setLanguage] = useState<Language>("ru");
  const [text, setText] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [confirmReset, setConfirmReset] = useState(false);
  const next = useRef(0);
  const send = useSendSandboxMessage({
    mutation: {
      onSuccess: (turn) => {
        setEntries((list) => [...list, { id: next.current++, role: "bot", turn }]);
      },
    },
  });
  const reset = useResetSandbox({
    mutation: {
      onSuccess: () => {
        setEntries([]);
        setConfirmReset(false);
      },
    },
  });
  const submit = () => {
    const question = text.trim();
    if (question === "" || send.isPending) return;
    setEntries((list) => [...list, { id: next.current++, role: "lead", text: question }]);
    setText("");
    send.mutate({ data: { text: question, language } });
  };
  return (
    <section aria-labelledby="pf-kb-sandbox">
      <Card
        title={
          <h2 className="pf-kb-section-title" id="pf-kb-sandbox">
            {t("sandbox.title")}
          </h2>
        }
        styles={{ body: { display: "flex", flexDirection: "column", gap: 12 } }}
      >
        <p className="pf-fp-sub">{t("sandbox.intro")}</p>
        <Alert
          type="warning"
          showIcon
          message={t("sandbox.paid")}
          description={t("sandbox.handoffNote")}
        />
        <ActionToggle
          label={t("sandbox.reset.button")}
          open={confirmReset}
          onToggle={setConfirmReset}
        >
          <form
            className="pf-fp-form"
            aria-label={t("sandbox.reset.button")}
            onSubmit={(event) => {
              event.preventDefault();
              reset.mutate();
            }}
          >
            <Consequence
              items={[t("sandbox.reset.step1"), t("sandbox.reset.step2"), t("sandbox.reset.step3")]}
            />
            <ErrorNote
              message={reset.isError ? kbErrorText(t, reset.error, i18n.language) : null}
            />
            <div className="pf-fp-row">
              <Button type="primary" danger htmlType="submit" loading={reset.isPending}>
                {t("sandbox.reset.submit")}
              </Button>
            </div>
          </form>
        </ActionToggle>
        <FormField id="kb-sandbox-language" label={t("sandbox.language")}>
          <Select
            id="kb-sandbox-language"
            value={language}
            style={{ minWidth: 160 }}
            options={LANGUAGES.map((value) => ({ value, label: t(`languages.${value}`) }))}
            onChange={setLanguage}
          />
        </FormField>
        <Thread entries={entries} language={language} />
        {send.isPending ? (
          <p className="pf-hint" role="status">
            {t("sandbox.thinking")}
          </p>
        ) : null}
        <ErrorNote message={send.isError ? kbErrorText(t, send.error, i18n.language) : null} />
        <form
          className="pf-fp-form"
          aria-label={t("sandbox.send")}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <FormField id="kb-sandbox-text" label={t("sandbox.placeholder")}>
            <Input.TextArea
              id="kb-sandbox-text"
              value={text}
              lang={language}
              autoSize={{ minRows: 2, maxRows: 6 }}
              maxLength={4000}
              onChange={(event) => {
                setText(event.target.value);
              }}
              onPressEnter={(event) => {
                if (!event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
            />
          </FormField>
          <Consequence items={[t("sandbox.step1"), t("sandbox.step2"), t("sandbox.step3")]} />
          <div className="pf-fp-row">
            <Button
              type="primary"
              htmlType="submit"
              loading={send.isPending}
              disabled={text.trim() === ""}
            >
              {t("sandbox.send")}
            </Button>
          </div>
        </form>
      </Card>
    </section>
  );
}
