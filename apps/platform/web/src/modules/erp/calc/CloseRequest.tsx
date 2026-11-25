import { Alert, App, Button, Input, Radio } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalcClose, CalcCloseReason } from "../../../shared/api/generated/model";
import {
  useCloseCalcRequest,
  useListCalcCloseReasons,
} from "../../../shared/api/generated/platform-bff";
import { Dialog } from "../../../shared/ui/Dialog";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { calcRef, useErrorText, useRefreshCalc } from "./api";

/** Что нужно «Закрыть заявку» от экрана: номер заявки и `close` из расчёта или карточки заявки. */
export interface Closable {
  number: string;
  close?: CalcClose;
}

/** Название причины на языке интерфейса; нет перевода — русское. */
function useReasonName(): (reason: CalcCloseReason) => string {
  const { i18n } = useTranslation();
  const lang = (["ru", "uz", "en"] as const).find((l) => i18n.language.startsWith(l)) ?? "ru";
  return (reason) => reason.name[lang] || reason.name.ru;
}

/** Окно «Закрыть заявку» (ЛХ-2): причина из справочника, комментарий — когда нужен; закрыть можно на любом шаге до проекта. */
function CloseModal({
  target,
  preselect,
  onClose,
}: {
  target: Closable;
  preselect?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const refresh = useRefreshCalc();
  const errorText = useErrorText();
  const nameOf = useReasonName();
  const commentId = useId();
  const reasons = useListCalcCloseReasons();
  const [code, setCode] = useState<string | null>(preselect ?? null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const quoteSent = target.close?.quote_sent === true;
  const close = useCloseCalcRequest({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("close.done"));
        onClose();
      },
      onError: (e) => {
        setError(errorText(e));
      },
    },
  });
  const items = reasons.data?.items ?? [];
  const chosen = items.find((row) => row.code === code) ?? null;
  const text = comment.trim();
  const ready = chosen !== null && (!chosen.requires_comment || text !== "");
  return (
    <Dialog
      open
      title={t("close.title", { number: target.number })}
      onCancel={onClose}
      cancelLabel={t("close.cancel")}
      okLabel={t("close.submit")}
      danger
      okDisabled={!ready}
      loading={close.isPending}
      onOk={() => {
        if (!chosen) return;
        setError(null);
        close.mutate({
          number: calcRef(target.number),
          data: { reason: chosen.code, ...(text ? { comment: text } : {}) },
        });
      }}
    >
      <div className="pf-calc-stack">
        <p>{t("close.text")}</p>
        {quoteSent ? <Alert type="info" showIcon message={t("close.quoteSent")} /> : null}
        {reasons.isError ? <ErrorNote message={t("close.reasonsError")} /> : null}
        <Radio.Group
          aria-label={t("close.reason")}
          value={code}
          onChange={(event) => {
            setCode(String(event.target.value));
          }}
        >
          <div className="pf-calc-stack">
            {items.map((row) => (
              <Radio
                key={row.code}
                value={row.code}
                disabled={quoteSent && !row.allowed_after_quote_sent}
              >
                {nameOf(row)}
              </Radio>
            ))}
          </div>
        </Radio.Group>
        {chosen ? (
          <FormField
            id={commentId}
            label={t("close.comment")}
            hint={chosen.requires_comment ? t("close.commentRequired") : undefined}
          >
            <Input.TextArea
              id={commentId}
              value={comment}
              maxLength={2000}
              rows={3}
              aria-required={chosen.requires_comment}
              aria-describedby={chosen.requires_comment ? `${commentId}-hint` : undefined}
              onChange={(event) => {
                setComment(event.target.value);
              }}
            />
          </FormField>
        ) : null}
        <ErrorNote message={error} />
      </div>
    </Dialog>
  );
}

/**
 * «Закрыть заявку» — одно действие везде, где открыта заявка до проекта: шапка расчёта, окно «Задание», карточка заявки без
 * расчёта. Видна только когда `close.allowed` (заявка до проекта, не закрыта, сотрудник — ответственный или держатель зоны
 * продаж). `preselect` — причина, выбранная заранее (после отказа клиента от КП — «Клиент передумал»).
 */
export function CloseRequestButton({
  target,
  preselect,
  size,
}: {
  target: Closable;
  preselect?: string;
  size?: "small";
}) {
  const { t } = useTranslation("calc");
  const [open, setOpen] = useState(false);
  if (target.close?.allowed !== true) return null;
  return (
    <>
      <Button
        danger
        size={size}
        onClick={() => {
          setOpen(true);
        }}
      >
        {t("close.button")}
      </Button>
      {open ? (
        <CloseModal
          target={target}
          preselect={preselect}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

/** Заявка закрыта через «Закрыть заявку»: причина и комментарий словами, что дальше. */
export function ClosedNote({ close }: { close?: CalcClose }) {
  const { t } = useTranslation("calc");
  const nameOf = useReasonName();
  const reasons = useListCalcCloseReasons();
  const code = close?.reason;
  if (!code) return null;
  const row = reasons.data?.items.find((item) => item.code === code);
  return (
    <Alert
      type="info"
      showIcon
      message={t("close.closed", { reason: row ? nameOf(row) : code })}
      description={close.comment ? close.comment : t("close.closedNext")}
    />
  );
}
