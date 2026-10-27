import { App, Button, Checkbox, Input } from "antd";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import type { QuoteApprovalCard, QuoteSendChannel } from "../../../shared/api/generated/model";
import { useDecideQuoteApproval } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Checklist } from "../../../shared/ui/Checklist";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { decisionReason, failedCodes, isTerminal, useRefreshApprovals } from "../decision/errors";
import { type ApprovalDraft, clearDraft, readDraft, writeDraft } from "./draft";
import { channelStates, checklistItems, defaultChannels, lateWarning, redBlockers } from "./model";

type Action = "approve" | "return";

export interface ApprovalFormProps {
  quote: QuoteApprovalCard;
  /** Лист на телефоне: кнопки решения закреплены внизу */
  variant?: "panel" | "sheet";
  /** Решение принято и сохранено (лист закрывается) */
  onDone?: () => void;
}

/**
 * Боковое окно «Одобрение» КП (SPEC-v3 §7.3, UX-оценка P0-4): чек-лист с датой и автором каждой строки, каналы отправки по
 * контакту клиента, главная кнопка «Одобрить КП → отправить клиенту» с блоком «Что произойдёт», «Вернуть на доработку»
 * (комментарий обязателен). Главная кнопка неактивна, пока EDS не разрешает `approve`, и подписана, какой пункт не зелёный:
 * проверку чек-листа делает EDS, форма её не дублирует. Строка «срок» — предупреждение, не блок (C1-G-1).
 */
export function ApprovalForm({ quote, variant = "panel", onDone }: ApprovalFormProps) {
  const { t } = useTranslation("quotes");
  const { me } = useAuth();
  const { date } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshApprovals();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;

  const states = channelStates(quote.channels);
  const [saved] = useState(() => readDraft(me.id, quote.id));
  const [state, setState] = useState<ApprovalDraft>(() => saved ?? { comment: "", channels: null });
  const [failure, setFailure] = useState<{ action: Action; error: unknown } | null>(null);
  const [pendingAction, setPendingAction] = useState<Action | null>(null);

  useEffect(() => {
    writeDraft(me.id, quote.id, state);
  }, [me.id, quote.id, state]);

  const chosen = (state.channels ?? defaultChannels(states)).filter((c) =>
    states.some((s) => s.channel === c && s.available),
  );
  const comment = state.comment.trim();
  const blockers = redBlockers(quote.checklist);
  const late = lateWarning(quote.checklist);
  const canApprove = quote.allowed_decisions.includes("approve");
  const canReturn = quote.allowed_decisions.includes("return");

  const decide = useDecideQuoteApproval({
    mutation: {
      onSuccess: (card, variables) => {
        clearDraft(me.id, quote.id);
        void refresh();
        const action: Action = variables.data.decision === "approve" ? "approve" : "return";
        void message.success(
          action === "approve"
            ? t("form.done.approve", { number: card.number, outgoing: card.outgoing_number ?? "" })
            : t("form.done.return", { number: card.number }),
        );
        onDone?.();
      },
      onError: (error, variables) => {
        const action: Action = variables.data.decision === "approve" ? "approve" : "return";
        // Решено другим или заменено новой версией: вводить больше нечего — обновляем карточку и говорим словами.
        if (isTerminal(error)) {
          clearDraft(me.id, quote.id);
          void message.error(failureText(action, error));
        }
        void refresh();
        setFailure({ action, error });
      },
    },
  });

  const failureText = (action: Action, error: unknown): string => {
    const reason = decisionReason(error);
    const items = failedCodes(error)
      .map((code) => t(`form.blockedItem.${code}`, { defaultValue: code }))
      .join(", ");
    const key =
      reason === "checklist_not_green" && items === "" ? "checklist_not_green_plain" : reason;
    return t(`form.failed.${action}`, { reason: t(`form.reasons.${key}`, { items }) });
  };

  const patch = (change: Partial<ApprovalDraft>) => {
    setState((prev) => ({ ...prev, ...change }));
    setFailure(null);
  };
  const toggle = (channel: QuoteSendChannel, on: boolean) => {
    const next = on ? [...chosen, channel] : chosen.filter((c) => c !== channel);
    patch({ channels: next });
  };

  const blockedText =
    blockers.length > 0
      ? t("form.blocked.checklist", {
          items: blockers.map((code) => t(`form.blockedItem.${code}`)).join(", "),
        })
      : !canApprove
        ? t("form.blocked.generic")
        : null;

  const channelNames = chosen.map((c) => t(`form.channels.${c}.name`)).join(", ");
  const consequence = [
    t("form.consequence.step1"),
    chosen.length > 0
      ? t("form.consequence.step2", { channels: channelNames })
      : t("form.consequence.step2None"),
    t("form.consequence.step3"),
  ];

  return (
    <form
      className={`pf-dec pf-dec--${variant}`}
      aria-label={t("form.name")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!canApprove || decide.isPending) return;
        setFailure(null);
        setPendingAction("approve");
        decide.mutate({
          id: quote.id,
          data: { decision: "approve", channels: chosen },
        });
      }}
    >
      {saved && saved.comment !== "" ? <p className="pf-hint">{t("form.draft")}</p> : null}

      <fieldset className="pf-dec-fieldset">
        <legend>{t("form.checklist.legend")}</legend>
        <Checklist
          items={checklistItems(quote.checklist, t, date)}
          label={t("form.checklist.legend")}
        />
        {late ? (
          <p className="pf-dec-warn" role="note">
            {t("form.checklist.lateNote", { due: quote.due ? date(quote.due) : "—" })}
          </p>
        ) : null}
      </fieldset>

      <fieldset className="pf-dec-fieldset" aria-describedby={id("channels-hint")}>
        <legend>{t("form.channels.legend")}</legend>
        <p className="pf-hint" id={id("channels-hint")}>
          {quote.channels === null
            ? t("form.channels.unknown")
            : quote.channels.contact_name
              ? t("form.channels.contact", { name: quote.channels.contact_name })
              : t("form.channels.hint")}
        </p>
        {states.map((s) => (
          <div className="pf-dec-channel" key={s.channel}>
            <Checkbox
              checked={chosen.includes(s.channel)}
              disabled={!s.available || decide.isPending}
              aria-describedby={s.reason ? id(`channel-${s.channel}`) : undefined}
              onChange={(event) => {
                toggle(s.channel, event.target.checked);
              }}
            >
              {t(`form.channels.${s.channel}.name`)}
            </Checkbox>
            {s.reason ? (
              <span className="pf-hint" id={id(`channel-${s.channel}`)}>
                {t(`form.channels.unavailable.${s.reason}`)}
              </span>
            ) : null}
          </div>
        ))}
      </fieldset>

      <Consequence title={t("form.consequence.title")} items={consequence} />

      <fieldset className="pf-dec-fieldset">
        <legend>{t("form.other.title")}</legend>
        <FormField
          id={id("comment")}
          label={t("form.other.comment")}
          hint={t("form.other.commentHint")}
        >
          <Input.TextArea
            id={id("comment")}
            value={state.comment}
            maxLength={4000}
            autoSize={{ minRows: 2, maxRows: 6 }}
            aria-describedby={`${id("comment")}-hint`}
            onChange={(event) => {
              patch({ comment: event.target.value });
            }}
          />
        </FormField>
      </fieldset>

      <ErrorNote message={failure ? failureText(failure.action, failure.error) : null} />

      <div className="pf-dec-actions">
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={decide.isPending && pendingAction === "approve"}
          disabled={!canApprove || decide.isPending}
          aria-describedby={blockedText ? id("blocked") : undefined}
        >
          {t("form.submit")}
        </Button>
        {blockedText ? (
          <p className="pf-hint" id={id("blocked")}>
            {blockedText}
          </p>
        ) : null}
        <div className="pf-dec-secondary pf-dec-secondary--single">
          <Button
            block
            loading={decide.isPending && pendingAction === "return"}
            disabled={!canReturn || decide.isPending || comment === ""}
            aria-describedby={comment === "" ? id("disabled") : undefined}
            onClick={() => {
              setFailure(null);
              setPendingAction("return");
              decide.mutate({ id: quote.id, data: { decision: "return", comment } });
            }}
          >
            {t("form.other.return")}
          </Button>
        </div>
        {comment === "" ? (
          <p className="pf-hint" id={id("disabled")}>
            {t("form.other.disabled")}
          </p>
        ) : null}
      </div>
    </form>
  );
}
