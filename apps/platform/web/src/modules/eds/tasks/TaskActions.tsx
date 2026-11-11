import { App, Button, Card, Input } from "antd";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { LetterCard, LetterInstruction } from "../../../shared/api/generated/model";
import {
  useAcknowledgeLetter,
  useCompleteInstruction,
  useRequestInstructionExtension,
} from "../../../shared/api/generated/platform-bff";
import { useAuth } from "../../../app/auth/useAuth";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { useResolutionKindName } from "../dictionaries";
import { fieldsOf, reasonOf, useRefreshLetters } from "../inbox/api";
import { AttachmentsField } from "../new/AttachmentsField";
import type { Attachment } from "../new/formModel";
import { OutcomeMenu } from "./LetterOutcomes";
import { ownDraftReply } from "./replyModel";
import { completeBody } from "./taskModel";

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | null | undefined;
  children: ReactNode;
}) {
  return (
    <div className="pf-fp-field">
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? (
        <span className="pf-field-error" id={`${id}-error`} role="alert">
          {error}
        </span>
      ) : null}
      {hint ? (
        <span className="pf-hint" id={`${id}-hint`}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

const described = (id: string, hint: boolean, error: boolean) =>
  [error ? `${id}-error` : "", hint ? `${id}-hint` : ""].filter(Boolean).join(" ") || undefined;

/** «Исполнено» (SPEC-v3 §3.2a п. 3): отчёт — текст и файлы, или номер отправленного ИСХ. Проверяет EDS. */
function CompleteForm({ instruction }: { instruction: LetterInstruction }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const ids = useId();
  const [report, setReport] = useState("");
  const [outgoing, setOutgoing] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [empty, setEmpty] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const uploading = attachments.some((a) => a.status === "uploading");
  const complete = useCompleteInstruction({
    mutation: {
      onSuccess: () => {
        void refresh();
        void message.success(t("tasks.complete.done"));
      },
      onError: setFailure,
    },
  });
  const outgoingError = fieldsOf(failure).includes("outgoing_number");
  return (
    <form
      className="pf-fp-form"
      aria-label={t("tasks.complete.title")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setFailure(null);
        const body = completeBody(report, attachments, outgoing);
        setEmpty(body === null);
        if (body === null) {
          window.setTimeout(() => document.getElementById(`${ids}-report`)?.focus(), 0);
          return;
        }
        complete.mutate({ id: instruction.id, data: body });
      }}
    >
      <h3 className="pf-res-subhead">{t("tasks.complete.title")}</h3>
      <Field
        id={`${ids}-report`}
        label={t("tasks.complete.report")}
        hint={t("tasks.complete.reportHint")}
        error={empty ? t("tasks.complete.error") : null}
      >
        <Input.TextArea
          id={`${ids}-report`}
          value={report}
          maxLength={10000}
          autoSize={{ minRows: 3, maxRows: 10 }}
          status={empty ? "error" : undefined}
          aria-invalid={empty || undefined}
          aria-describedby={described(`${ids}-report`, true, empty)}
          onChange={(event) => {
            setReport(event.target.value);
            setEmpty(false);
          }}
        />
      </Field>
      <Field id={`${ids}-files`} label={t("tasks.complete.files")}>
        <AttachmentsField id={`${ids}-files`} value={attachments} onChange={setAttachments} />
      </Field>
      <Field
        id={`${ids}-outgoing`}
        label={t("tasks.complete.outgoing")}
        hint={t("tasks.complete.outgoingHint")}
        error={outgoingError ? t("form.reasons.not_found") : null}
      >
        <Input
          id={`${ids}-outgoing`}
          value={outgoing}
          maxLength={32}
          autoComplete="off"
          placeholder="ИСХ-014/26"
          status={outgoingError ? "error" : undefined}
          aria-invalid={outgoingError || undefined}
          aria-describedby={described(`${ids}-outgoing`, true, outgoingError)}
          onChange={(event) => {
            setOutgoing(event.target.value);
            setFailure(null);
          }}
        />
      </Field>
      <ErrorNote
        message={
          failure ? t("tasks.failed", { reason: t(`form.reasons.${reasonOf(failure)}`) }) : null
        }
      />
      <div className="pf-fp-row">
        <Button type="primary" htmlType="submit" loading={complete.isPending} disabled={uploading}>
          {t("tasks.complete.submit")}
        </Button>
      </div>
    </form>
  );
}

/** «Запросить перенос» (SPEC-v3 §3.2a п. 3–4): новая дата и причина; срочные не продлеваются (решает EDS, экран подсказывает). */
function ExtensionForm({
  instruction,
  urgent,
}: {
  instruction: LetterInstruction;
  urgent: boolean;
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const ids = useId();
  const [newDue, setNewDue] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{ due?: boolean; reason?: boolean }>({});
  const [failure, setFailure] = useState<unknown>(null);
  const request = useRequestInstructionExtension({
    mutation: {
      onSuccess: () => {
        void refresh();
        void message.success(t("tasks.ext.done"));
      },
      onError: setFailure,
    },
  });
  const pending = instruction.extensions.find((e) => e.status === "pending");
  if (pending) {
    return (
      <section aria-labelledby={`${ids}-title`}>
        <h3 className="pf-res-subhead" id={`${ids}-title`}>
          {t("tasks.ext.title")}
        </h3>
        <p className="pf-hint" role="status">
          {t("tasks.ext.pending", { date: date(pending.new_due) })}
        </p>
      </section>
    );
  }
  return (
    <form
      className="pf-fp-form"
      aria-label={t("tasks.ext.title")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setFailure(null);
        const found = { due: !newDue || newDue <= instruction.due, reason: reason.trim() === "" };
        setErrors(found);
        if (found.due || found.reason) {
          const target = found.due ? `${ids}-due` : `${ids}-reason`;
          window.setTimeout(() => document.getElementById(target)?.focus(), 0);
          return;
        }
        request.mutate({ id: instruction.id, data: { new_due: newDue, reason: reason.trim() } });
      }}
    >
      <h3 className="pf-res-subhead">{t("tasks.ext.title")}</h3>
      {/* Росархив 5.14: срок срочного не продлевается — запросить можно, директор может только отклонить */}
      {urgent ? <p className="pf-hint">{t("tasks.ext.urgent")}</p> : null}
      <div className="pf-newdoc-row">
        <Field
          id={`${ids}-due`}
          label={t("tasks.ext.newDue")}
          error={errors.due ? t("tasks.ext.errorDue", { date: date(instruction.due) }) : null}
        >
          <DateField
            id={`${ids}-due`}
            value={newDue}
            min={instruction.due}
            status={errors.due ? "error" : undefined}
            aria-invalid={errors.due || undefined}
            aria-describedby={described(`${ids}-due`, false, Boolean(errors.due))}
            onChange={(next) => {
              setNewDue(next);
              setErrors((prev) => ({ ...prev, due: false }));
            }}
          />
        </Field>
      </div>
      <Field
        id={`${ids}-reason`}
        label={t("tasks.ext.reason")}
        error={errors.reason ? t("tasks.ext.errorReason") : null}
      >
        <Input.TextArea
          id={`${ids}-reason`}
          value={reason}
          maxLength={2000}
          autoSize={{ minRows: 2, maxRows: 6 }}
          status={errors.reason ? "error" : undefined}
          aria-invalid={errors.reason || undefined}
          aria-describedby={described(`${ids}-reason`, false, Boolean(errors.reason))}
          onChange={(event) => {
            setReason(event.target.value);
            setErrors((prev) => ({ ...prev, reason: false }));
          }}
        />
      </Field>
      <ErrorNote
        message={
          failure ? t("tasks.failed", { reason: t(`form.reasons.${reasonOf(failure)}`) }) : null
        }
      />
      <div className="pf-fp-row">
        <Button htmlType="submit" loading={request.isPending}>
          {t("tasks.ext.submit")}
        </Button>
      </div>
    </form>
  );
}

/** Моё поручение: «Ответить» (письмо «в ответ на» у любого поручения, решение владельца 2026-11-11), «Исполнено», «Запросить перенос». */
export function MyInstruction({
  letter,
  instruction,
}: {
  letter: LetterCard;
  instruction: LetterInstruction;
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { me } = useAuth();
  const kindName = useResolutionKindName();
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("tasks.mine")}</h2>}>
      <p className={instruction.overdue ? "pf-instr-due pf-instr-due--overdue" : "pf-instr-due"}>
        <strong>{kindName(instruction.kind)}</strong> ·{" "}
        {t("instr.due", { date: date(instruction.due) })}
        {instruction.overdue ? ` · ${t("instr.overdue")}` : ""}
      </p>
      <p className="pf-letters-summary">{instruction.text}</p>
      {instruction.kind !== "info" ? (
        <div className="pf-instr-reply">
          {/* P4 (B-P8B-4): письмо-ответ готовит любой исполнитель; без права регистрировать — передаёт делопроизводителю.
              EDS-REPLY-1: форма берёт корреспондента, ИНН, почту и тему из письма; начатый ответ продолжается, а не дублируется. */}
          {ownDraftReply(letter, me.id) ? (
            <LinkButton to={`/eds/new?draft=${ownDraftReply(letter, me.id)?.document_id ?? ""}`}>
              {t("reply.continue")}
            </LinkButton>
          ) : (letter.replies ?? []).some((r) => r.state === "registration_requested") ? null : (
            <LinkButton
              type="primary"
              to={`/eds/new?type=letter&reply_to=${encodeURIComponent(letter.number)}&reply_id=${encodeURIComponent(letter.id)}`}
            >
              {t("tasks.reply.prepare")}
            </LinkButton>
          )}
          <p className="pf-hint">{t("tasks.reply.hint", { number: letter.number })}</p>
        </div>
      ) : null}
      <CompleteForm instruction={instruction} />
      <ExtensionForm instruction={instruction} urgent={letter.urgent} />
      <div className="pf-fp-row">
        <OutcomeMenu letter={letter} instruction={instruction} />
      </div>
    </Card>
  );
}

/** «Ознакомиться» (SPEC-v3 §3.2a п. 2): отметка «Ознакомлен» с датой. */
export function AcquaintAction({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const [failure, setFailure] = useState<unknown>(null);
  const acknowledge = useAcknowledgeLetter({
    mutation: {
      onSuccess: () => {
        void refresh();
        void message.success(t("tasks.acq.done"));
      },
      onError: setFailure,
    },
  });
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("tasks.acq.title")}</h2>}>
      <p>{t("tasks.acq.text")}</p>
      <ErrorNote
        message={
          failure ? t("tasks.failed", { reason: t(`form.reasons.${reasonOf(failure)}`) }) : null
        }
      />
      <Button
        type="primary"
        loading={acknowledge.isPending}
        onClick={() => {
          setFailure(null);
          acknowledge.mutate({ id: letter.id });
        }}
      >
        {t("tasks.acq.submit")}
      </Button>
    </Card>
  );
}
