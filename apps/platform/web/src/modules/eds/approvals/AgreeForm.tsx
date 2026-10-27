import { App, Button, Input } from "antd";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import type { MemoApprovalCard } from "../../../shared/api/generated/model";
import { useDecideMemoApproval } from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { decisionReason, isTerminal, useRefreshApprovals } from "../decision/errors";
import { clearComment, readComment, writeComment } from "./draft";
import { nextStepLabel } from "./model";

type Action = "approve" | "return" | "reject";

export interface AgreeFormProps {
  memo: MemoApprovalCard;
  /** Лист на телефоне: кнопки решения закреплены внизу */
  variant?: "panel" | "sheet";
  /** Решение принято и сохранено (лист закрывается) */
  onDone?: () => void;
}

/**
 * Боковое окно «Согласование» (SPEC-v3 §3.2, §7.3): комментарий, главная кнопка «Согласовать» с блоком «Что произойдёт»,
 * «Вернуть на доработку» и «Отклонить» (комментарий обязателен: кнопки неактивны с подписью, пока он пуст). Введённый
 * комментарий сохраняется в браузере — ошибка решения его не стирает. Решает EDS (чей шаг, закрыт ли маршрут).
 */
export function AgreeForm({ memo, variant = "panel", onDone }: AgreeFormProps) {
  const { t } = useTranslation("approvals");
  const { me } = useAuth();
  const { message } = App.useApp();
  const refresh = useRefreshApprovals();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;

  const [saved] = useState(() => readComment(me.id, memo.approval_id));
  const [comment, setComment] = useState(saved ?? "");
  const [failure, setFailure] = useState<{ action: Action; error: unknown } | null>(null);
  const [pendingAction, setPendingAction] = useState<Action | null>(null);

  useEffect(() => {
    writeComment(me.id, memo.approval_id, comment);
  }, [me.id, memo.approval_id, comment]);

  const failureText = (action: Action, error: unknown): string =>
    t(`form.failed.${action}`, { reason: t(`form.reasons.${decisionReason(error)}`) });

  const decide = useDecideMemoApproval({
    mutation: {
      onSuccess: (_card, variables) => {
        clearComment(me.id, memo.approval_id);
        void refresh();
        void message.success(t(`form.done.${variables.data.decision}`));
        onDone?.();
      },
      onError: (error, variables) => {
        const action = variables.data.decision;
        // Решено другим или шаг не ваш: вводить больше нечего — обновляем карточку и говорим словами.
        if (isTerminal(error)) {
          clearComment(me.id, memo.approval_id);
          void message.error(failureText(action, error));
        }
        void refresh();
        setFailure({ action, error });
      },
    },
  });

  const text = comment.trim();
  const next = nextStepLabel(memo.steps);
  const may = (d: Action) => memo.allowed_decisions.includes(d);
  const busy = decide.isPending;

  const send = (decision: Action) => {
    setFailure(null);
    setPendingAction(decision);
    decide.mutate({
      id: memo.approval_id,
      data:
        decision === "approve" ? { decision, comment: text || null } : { decision, comment: text },
    });
  };

  return (
    <form
      className={`pf-dec pf-dec--${variant}`}
      aria-label={t("form.name")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (may("approve") && !busy) send("approve");
      }}
    >
      {saved ? <p className="pf-hint">{t("form.draft")}</p> : null}

      <FormField id={id("comment")} label={t("form.comment.label")} hint={t("form.comment.hint")}>
        <Input.TextArea
          id={id("comment")}
          value={comment}
          maxLength={4000}
          autoSize={{ minRows: 3, maxRows: 8 }}
          aria-describedby={`${id("comment")}-hint`}
          onChange={(event) => {
            setComment(event.target.value);
            setFailure(null);
          }}
        />
      </FormField>

      <Consequence
        title={t("form.consequence.title")}
        items={[
          t("form.consequence.step1"),
          next ? t("form.consequence.step2Next", { label: next }) : t("form.consequence.step2"),
          t("form.consequence.step3"),
        ]}
      />

      <ErrorNote message={failure ? failureText(failure.action, failure.error) : null} />

      <div className="pf-dec-actions">
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={busy && pendingAction === "approve"}
          disabled={!may("approve") || busy}
        >
          {t("form.submit")}
        </Button>
        <div className="pf-dec-secondary">
          <Button
            block
            loading={busy && pendingAction === "return"}
            disabled={!may("return") || busy || text === ""}
            aria-describedby={text === "" ? id("disabled") : undefined}
            onClick={() => {
              send("return");
            }}
          >
            {t("form.return")}
          </Button>
          <Button
            block
            danger
            loading={busy && pendingAction === "reject"}
            disabled={!may("reject") || busy || text === ""}
            aria-describedby={text === "" ? id("disabled") : undefined}
            onClick={() => {
              send("reject");
            }}
          >
            {t("form.reject")}
          </Button>
        </div>
        {text === "" ? (
          <p className="pf-hint" id={id("disabled")}>
            {t("form.disabled")}
          </p>
        ) : null}
      </div>
    </form>
  );
}
