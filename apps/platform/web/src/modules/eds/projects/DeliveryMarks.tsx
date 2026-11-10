import { App, Button, Input, Modal } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ProjectDeliveryAction,
  ProjectFulfillment,
} from "../../../shared/api/generated/model";
import { useMarkEdsProjectDelivery } from "../../../shared/api/generated/platform-bff";
import { ApiError } from "../../../shared/api/errors";
import { companyDayKey, companyToday } from "../../../shared/lib/dates";
import { DateField } from "../../../shared/ui/DateField";
import { FileField } from "../../../shared/ui/FileField";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { projectRef } from "./api";
import { useApplyCard } from "./useProjectMutations";

/** Подтверждение доставки: изображение, PDF или документ до 20 МБ — как у вложений ERP (`validate_document_upload`). */
const PROOF_ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.gif,.doc,.docx,.xls,.xlsx,.csv,.txt";
const PROOF_MAX = 20 * 1024 * 1024;

/**
 * Отметки доставки клиенту (L0-1): «Отправлено, в пути» и «Доставлено» по всему проекту. Какие отметки доступны — решает
 * сервер (`fulfillment.actions`: статус исполнения и право склада). После «Доставлено» клиент принимает поставку в кабинете.
 * Эталоны: Odoo — «Validate» доставки и Proof of Delivery, Business Central — «Posted Sales Shipment» с номером отправления,
 * SAP S/4HANA — «Proof of Delivery».
 */
export function DeliveryActions({
  objectId,
  fulfillment,
}: {
  objectId: string;
  fulfillment: ProjectFulfillment;
}) {
  const { t } = useTranslation("projects");
  const [open, setOpen] = useState<ProjectDeliveryAction | null>(null);
  if (fulfillment.actions.length === 0) return null;
  return (
    <div className="pf-dec-row">
      {fulfillment.actions.map((action) => (
        <Button
          key={action}
          onClick={() => {
            setOpen(action);
          }}
        >
          {t(`card.delivery.${action}`)}
        </Button>
      ))}
      {open ? (
        <DeliveryDialog
          objectId={objectId}
          action={open}
          fulfillment={fulfillment}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
    </div>
  );
}

function DeliveryDialog({
  objectId,
  action,
  fulfillment,
  onClose,
}: {
  objectId: string;
  action: ProjectDeliveryAction;
  fulfillment: ProjectFulfillment;
  onClose: () => void;
}) {
  const { t } = useTranslation("projects");
  const { message } = App.useApp();
  const apply = useApplyCard(objectId);
  const today = companyToday();
  // Доставка не раньше отправки: та же проверка, что у сервера.
  const shippedOn =
    action === "delivered" && fulfillment.shipped_at
      ? (companyDayKey(fulfillment.shipped_at) ?? undefined)
      : undefined;
  const ids = { date: useId(), waybill: useId(), file: useId() };
  const [onDate, setOnDate] = useState(today);
  const [waybill, setWaybill] = useState(fulfillment.tracking_number ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [touched, setTouched] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const mark = useMarkEdsProjectDelivery({
    mutation: {
      onSuccess: (card) => {
        apply(card);
        void message.success(t(`card.delivery.done.${action}`));
        onClose();
      },
      onError: (error) => {
        setFailure(error instanceof ApiError ? error.message : t("card.delivery.failed"));
      },
    },
  });
  const badDate = !onDate || onDate > today || (shippedOn !== undefined && onDate < shippedOn);
  const file = files[0];
  const submit = () => {
    setTouched(true);
    if (badDate) return;
    setFailure(null);
    mark.mutate({
      ref: projectRef(objectId),
      data: {
        action,
        on_date: onDate,
        ...(waybill.trim() ? { waybill: waybill.trim() } : {}),
        ...(action === "delivered" && file ? { file } : {}),
      },
    });
  };
  const title = t(`card.delivery.dialog.${action}`);
  return (
    <Modal
      open
      width={480}
      title={title}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("card.delivery.dialog.cancel")}
        </Button>,
        <Button key="submit" type="primary" loading={mark.isPending} onClick={submit}>
          {t("card.delivery.dialog.submit")}
        </Button>,
      ]}
    >
      <form
        className="pf-fp-form"
        aria-label={title}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <FormField
          id={ids.date}
          label={t(`card.delivery.dialog.date.${action}`)}
          hint={touched && badDate ? t("card.delivery.dialog.dateInvalid") : undefined}
        >
          <DateField
            id={ids.date}
            aria-required
            allowClear={false}
            min={shippedOn}
            max={today}
            status={touched && badDate ? "error" : undefined}
            value={onDate}
            onChange={setOnDate}
          />
        </FormField>
        <FormField
          id={ids.waybill}
          label={t("card.delivery.dialog.waybill")}
          hint={t("card.delivery.dialog.waybillHint")}
        >
          <Input
            id={ids.waybill}
            maxLength={128}
            value={waybill}
            aria-describedby={`${ids.waybill}-hint`}
            onChange={(event) => {
              setWaybill(event.target.value);
            }}
          />
        </FormField>
        {action === "delivered" ? (
          <FormField
            id={ids.file}
            label={t("card.delivery.dialog.file")}
            hint={t("card.delivery.dialog.fileHint")}
          >
            <FileField
              id={ids.file}
              value={files}
              onChange={setFiles}
              accept={PROOF_ACCEPT}
              maxSize={PROOF_MAX}
              aria-describedby={`${ids.file}-hint`}
            />
          </FormField>
        ) : null}
        <ErrorNote message={failure} />
      </form>
    </Modal>
  );
}
