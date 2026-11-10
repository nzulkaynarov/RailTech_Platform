import { App, Button, Card, Input, Modal } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  OnBehalfChannel,
  QuoteApprovalCard,
  QuoteClientDecision,
  QuoteClientDecisionInDecision,
} from "../../../shared/api/generated/model";
import { useRecordQuoteClientDecision } from "../../../shared/api/generated/platform-bff";
import { ApiError } from "../../../shared/api/errors";
import { companyToday } from "../../../shared/lib/dates";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { FileField } from "../../../shared/ui/FileField";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { OnBehalfFields, OnBehalfNote } from "../../../shared/ui/OnBehalf";
import { useRefreshApprovals } from "../decision/errors";

/** Подтверждение клиента: изображение, PDF или документ до 20 МБ — как у вложений ERP (`validate_document_upload`). */
const EVIDENCE_ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.gif,.doc,.docx,.xls,.xlsx,.csv,.txt";
const EVIDENCE_MAX = 20 * 1024 * 1024;

/** Текст отказа BFF: сообщение ERP словами (`message`), иначе — общий сбой. */
function failureText(error: unknown): string | null {
  return error instanceof ApiError ? error.message : null;
}

/**
 * Решение клиента по отправленному КП (A1 волны 18a, «Отметить за контрагента»): статус словом; пока КП ждёт решения, у того,
 * кто ведёт клиента, — «Клиент принял» / «Клиент отклонил» (записать по подтверждению клиента: письмо, переписка, скан).
 * Решение, записанное сотрудником, помечено значком «Отмечено сотрудником» — кто, канал, лицо клиента, файл.
 * Эталоны: Zoho «Mark as Accepted», HubSpot «Mark as signed», Salesforce Quote Status, Odoo Confirm.
 */
export function ClientDecisionCard({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const [open, setOpen] = useState<QuoteClientDecisionInDecision | null>(null);
  const decision = quote.client_decision;
  if (!decision) return null;
  return (
    <Card size="small" title={<h2 className="pf-dec-title">{t("card.clientDecision.title")}</h2>}>
      <DecisionBody decision={decision} />
      {decision.can_record ? (
        <div className="pf-dec-row">
          <Button
            type="primary"
            onClick={() => {
              setOpen("accept");
            }}
          >
            {t("card.clientDecision.accept")}
          </Button>
          <Button
            onClick={() => {
              setOpen("reject");
            }}
          >
            {t("card.clientDecision.reject")}
          </Button>
        </div>
      ) : null}
      {open ? (
        <ClientDecisionDialog
          quoteId={quote.id}
          decision={open}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
    </Card>
  );
}

function DecisionBody({ decision }: { decision: QuoteClientDecision }) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  const staff = decision.recorded_by_staff;
  const when =
    decision.decided_at && (decision.state === "accepted" || decision.state === "rejected")
      ? t(`card.clientDecision.${decision.state}At`, {
          date: date(decision.decided_at, "datetime"),
        })
      : null;
  return (
    <div className="pf-onbehalf-block">
      <p className="pf-dec-note">
        {t(`card.clientDecision.state.${decision.state}`)}
        {when ? <span className="pf-hint"> {when}</span> : null}
      </p>
      {decision.reason ? (
        <p className="pf-hint">{t("card.clientDecision.reason", { reason: decision.reason })}</p>
      ) : null}
      {staff ? (
        <>
          <OnBehalfNote
            channel={staff.channel}
            person={staff.counterparty_person}
            staff={staff.staff_name}
          />
          {staff.comment && staff.comment !== decision.reason ? (
            <p className="pf-hint">{staff.comment}</p>
          ) : null}
          {staff.evidence_url ? (
            <a className="pf-focusable" href={staff.evidence_url} download>
              {t("card.clientDecision.file", { name: staff.evidence_name ?? "" })}
            </a>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function ClientDecisionDialog({
  quoteId,
  decision,
  onClose,
}: {
  quoteId: string;
  decision: QuoteClientDecisionInDecision;
  onClose: () => void;
}) {
  const { t } = useTranslation("quotes");
  const { message } = App.useApp();
  const refresh = useRefreshApprovals();
  const today = companyToday();
  const ids = {
    channel: useId(),
    person: useId(),
    date: useId(),
    comment: useId(),
    file: useId(),
  };
  const [channel, setChannel] = useState<OnBehalfChannel | null>(null);
  const [person, setPerson] = useState("");
  const [occurredOn, setOccurredOn] = useState(today);
  const [comment, setComment] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [touched, setTouched] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const record = useRecordQuoteClientDecision({
    mutation: {
      onSuccess: () => {
        void refresh();
        void message.success(t(`card.clientDecision.dialog.done.${decision}`));
        onClose();
      },
      onError: (error) => {
        void refresh();
        setFailure(
          t("card.clientDecision.dialog.failed", {
            reason: failureText(error) ?? t("card.delivery.reason.send_failed"),
          }),
        );
      },
    },
  });
  const badDate = !occurredOn || occurredOn > today;
  const noComment = !comment.trim();
  const file = files[0];
  const submit = () => {
    setTouched(true);
    if (!channel || !person.trim() || badDate || noComment || !file) return;
    setFailure(null);
    record.mutate({
      id: quoteId,
      data: {
        decision,
        channel,
        counterparty_person: person.trim(),
        occurred_on: occurredOn,
        comment: comment.trim(),
        file,
      },
    });
  };
  const commentLabel =
    decision === "reject"
      ? t("card.clientDecision.dialog.commentReject")
      : t("card.clientDecision.dialog.comment");
  return (
    <Modal
      open
      width={480}
      title={t(`card.clientDecision.dialog.${decision}`)}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("card.clientDecision.dialog.cancel")}
        </Button>,
        <Button key="submit" type="primary" loading={record.isPending} onClick={submit}>
          {t("card.clientDecision.dialog.submit")}
        </Button>,
      ]}
    >
      <form
        className="pf-fp-form"
        aria-label={t(`card.clientDecision.dialog.${decision}`)}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <OnBehalfFields
          ids={ids}
          channel={channel}
          person={person}
          touched={touched}
          onChannel={setChannel}
          onPerson={setPerson}
        />
        <FormField
          id={ids.date}
          label={t("card.clientDecision.dialog.date")}
          hint={touched && badDate ? t("card.clientDecision.dialog.dateRequired") : undefined}
        >
          <DateField
            id={ids.date}
            aria-required
            allowClear={false}
            max={today}
            status={touched && badDate ? "error" : undefined}
            value={occurredOn}
            onChange={setOccurredOn}
          />
        </FormField>
        <FormField
          id={ids.comment}
          label={commentLabel}
          hint={touched && noComment ? t("card.clientDecision.dialog.commentRequired") : undefined}
        >
          <Input.TextArea
            id={ids.comment}
            aria-required
            rows={3}
            maxLength={2000}
            status={touched && noComment ? "error" : undefined}
            value={comment}
            onChange={(event) => {
              setComment(event.target.value);
            }}
          />
        </FormField>
        <FormField
          id={ids.file}
          label={t("card.clientDecision.dialog.file")}
          hint={
            touched && !file
              ? t("card.clientDecision.dialog.fileRequired")
              : t("card.clientDecision.dialog.fileHint")
          }
        >
          <FileField
            id={ids.file}
            value={files}
            onChange={setFiles}
            accept={EVIDENCE_ACCEPT}
            maxSize={EVIDENCE_MAX}
            aria-invalid={touched && !file}
            aria-describedby={`${ids.file}-hint`}
          />
        </FormField>
        <ErrorNote message={failure} />
      </form>
    </Modal>
  );
}
