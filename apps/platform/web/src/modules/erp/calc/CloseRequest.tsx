import { Alert, App, Button, Input, Radio } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalcCloseReason, CalcSheet } from "../../../shared/api/generated/model";
import {
  useCloseCalcRequest,
  useListCalcCloseReasons,
} from "../../../shared/api/generated/platform-bff";
import { Dialog } from "../../../shared/ui/Dialog";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { calcRef, useApplySheet, useErrorText } from "./api";

/** Название причины на языке интерфейса; нет перевода — русское. */
function useReasonName(): (reason: CalcCloseReason) => string {
  const { i18n } = useTranslation();
  const lang = (["ru", "uz", "en"] as const).find((l) => i18n.language.startsWith(l)) ?? "ru";
  return (reason) => reason.name[lang] || reason.name.ru;
}

/** Окно «Закрыть заявку» (ЛХ-2): причина из справочника, комментарий — когда нужен; закрыть можно на любом шаге до проекта. */
function CloseModal({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const nameOf = useReasonName();
  const commentId = useId();
  const reasons = useListCalcCloseReasons();
  const [code, setCode] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const quoteSent = sheet.close?.quote_sent === true;
  const close = useCloseCalcRequest({
    mutation: {
      onSuccess: (next) => {
        apply(next);
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
      title={t("close.title", { number: sheet.number })}
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
          number: calcRef(sheet.number),
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

/** «Закрыть заявку» в шапке карточки: только когда заявка до проекта, не закрыта и сотрудник вправе (`close.allowed`). */
export function CloseRequestButton({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const [open, setOpen] = useState(false);
  if (sheet.close?.allowed !== true) return null;
  return (
    <>
      <Button
        danger
        onClick={() => {
          setOpen(true);
        }}
      >
        {t("close.button")}
      </Button>
      {open ? (
        <CloseModal
          sheet={sheet}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

/** Заявка закрыта через «Закрыть заявку»: причина и комментарий словами, что дальше. */
export function ClosedNote({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const nameOf = useReasonName();
  const reasons = useListCalcCloseReasons();
  const code = sheet.close?.reason;
  if (!code) return null;
  const row = reasons.data?.items.find((item) => item.code === code);
  const comment = sheet.close?.comment;
  return (
    <Alert
      type="info"
      showIcon
      message={t("close.closed", { reason: row ? nameOf(row) : code })}
      description={comment ? comment : t("close.closedNext")}
    />
  );
}
