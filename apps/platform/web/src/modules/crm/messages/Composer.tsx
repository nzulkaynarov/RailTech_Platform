import { Alert, App, Button, Input, Segmented, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import type { ConversationCard } from "../../../shared/api/generated/model";
import {
  useAssistCrmReply,
  useListCrmReplyTemplates,
  useNoteCrmLead,
  useReplyCrmLead,
} from "../../../shared/api/generated/platform-bff";
import { useRefreshMessages } from "./actions";
import { type SendFailure, actionError, sendFailure } from "./labels";
import { fillTemplate } from "./logic";
import { newMessageKey } from "./sla";

export type ComposerMode = "self" | "note";

/**
 * Поле ответа: «От себя» (уходит клиенту в Telegram) или «Заметка команде» (клиенту не уходит), шаблоны и «Подсказать
 * ответ» (ИИ через CRM; текст вставляется в поле, отправляет человек). Ключ повтора создаётся на черновик и меняется вместе
 * с текстом: «Повторить» после «Telegram не ответил» шлёт тот же ключ — CRM не продублирует сообщение, а текст остаётся
 * в поле до успешной отправки.
 */
export function Composer({ card }: { card: ConversationCard }) {
  const { t } = useTranslation("messages");
  const { me } = useAuth();
  const { message } = App.useApp();
  const refresh = useRefreshMessages();
  const fieldId = useId();
  const hintId = useId();
  const [mode, setMode] = useState<ComposerMode>("self");
  const [text, setText] = useState("");
  const [key, setKey] = useState(newMessageKey);
  const [failed, setFailed] = useState<SendFailure | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mine = card.owner_mode === "manager" && card.assigned?.id === me.id;
  const templates = useListCrmReplyTemplates({ query: { staleTime: 60_000 } });

  const edit = (value: string) => {
    // Итог прежней отправки неизвестен: правленый текст уйдёт новым сообщением — говорим об этом прямо.
    if (failed?.unknown) setNotice(t("composer.editAfterUnknown"));
    setText(value);
    setKey(newMessageKey());
    setFailed(null);
  };
  const done = (note: string) => {
    setText("");
    setKey(newMessageKey());
    setFailed(null);
    setNotice(null);
    void message.success(note);
    refresh();
  };

  const reply = useReplyCrmLead({
    mutation: {
      onSuccess: () => {
        done(t("composer.sent"));
      },
      onError: (error) => {
        setFailed(sendFailure(t, error));
      },
    },
  });
  const note = useNoteCrmLead({
    mutation: {
      onSuccess: () => {
        done(t("composer.noteSaved"));
      },
      onError: (error) => {
        setFailed({ text: actionError(t, error), retry: false });
      },
    },
  });
  const assist = useAssistCrmReply({
    mutation: {
      onSuccess: (data) => {
        setText(data.text);
        setKey(newMessageKey());
        setFailed(null);
        setNotice(
          data.notice ? t(`composer.assistNotice.${data.notice}`) : t("composer.assistDone"),
        );
      },
      onError: (error) => {
        setNotice(actionError(t, error));
      },
    },
  });

  const blocked = mode === "self" && !mine;
  const busy = reply.isPending || note.isPending;
  const send = () => {
    const body = text.trim();
    if (!body || busy) return;
    setFailed(null);
    if (mode === "note") note.mutate({ lead: card.lead, data: { text: body } });
    else reply.mutate({ lead: card.lead, data: { text: body, client_message_id: key } });
  };

  return (
    <form
      className="pf-msg-composer"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <div className="pf-msg-composer-bar">
        <Segmented<ComposerMode>
          aria-label={t("composer.mode")}
          value={mode}
          onChange={(value) => {
            setMode(value);
            setFailed(null);
          }}
          options={[
            { value: "self", label: t("composer.self") },
            { value: "note", label: t("composer.note") },
          ]}
        />
        {mode === "self" && mine ? (
          <div className="pf-msg-composer-tools">
            <Select
              aria-label={t("composer.templates")}
              placeholder={t("composer.templatesPlaceholder")}
              value={null}
              size="small"
              style={{ minWidth: 180 }}
              showSearch
              optionFilterProp="label"
              loading={templates.isPending}
              options={(templates.data?.items ?? []).map((tpl) => ({
                value: tpl.id,
                label: tpl.title,
              }))}
              onChange={(id: number | null) => {
                const tpl = templates.data?.items.find((x) => x.id === id);
                if (tpl) edit(fillTemplate(tpl.text, card.language, card.name, me.name));
              }}
            />
            <Button
              size="small"
              loading={assist.isPending}
              onClick={() => {
                assist.mutate({
                  lead: card.lead,
                  data: text.trim() ? { mode: "improve", text: text.trim() } : { mode: "draft" },
                });
              }}
            >
              {t("composer.assist")}
            </Button>
          </div>
        ) : null}
      </div>
      <label htmlFor={fieldId} className="pf-msg-composer-label">
        {mode === "self" ? t("composer.selfLabel") : t("composer.noteLabel")}
      </label>
      <Input.TextArea
        id={fieldId}
        value={text}
        autoSize={{ minRows: 2, maxRows: 6 }}
        maxLength={4000}
        disabled={blocked}
        aria-describedby={hintId}
        onChange={(event) => {
          edit(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) send();
        }}
      />
      <div className="pf-msg-composer-foot">
        <span
          id={hintId}
          className={mode === "note" ? "pf-msg-hint pf-msg-hint--note" : "pf-msg-hint"}
        >
          {blocked
            ? t("composer.takeFirst")
            : mode === "self"
              ? t("composer.selfHint")
              : t("composer.noteHint")}
        </span>
        <Button type="primary" htmlType="submit" loading={busy} disabled={blocked || !text.trim()}>
          {mode === "self" ? t("composer.send") : t("composer.save")}
        </Button>
      </div>
      {notice ? (
        <p className="pf-msg-notice" role="status">
          {notice}
        </p>
      ) : null}
      {failed && !busy ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={failed.text}
          action={
            failed.retry ? (
              <Button size="small" danger onClick={send}>
                {t("composer.retry")}
              </Button>
            ) : undefined
          }
        />
      ) : null}
    </form>
  );
}
