import { App, Button, Input, Select } from "antd";
import { Dialog } from "../../../shared/ui/Dialog";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { LeadRequestType } from "../../../shared/api/generated/model";
import {
  useAssignCrmLead,
  useHandOverCrmLead,
  useListCrmLeadColleagues,
  useListCrmLeadManagers,
} from "../../../shared/api/generated/platform-bff";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { useRefreshMessages } from "./actions";
import { actionError } from "./labels";

import "./messages.css";

const TYPES: readonly LeadRequestType[] = ["goods", "services", "project", "other"];

/**
 * «Передать менеджеру» (D17G-1, DECISIONS 2026-11-01 п. 1): первая линия разбирает лида и передаёт его менеджеру с запиской —
 * кому (держатели работы с клиентом), записка (обязательна), тип обращения (необязателен). Клиенту ничего не уходит; лид
 * получает ответственного, у менеджера — строка в «Моих задачах» и уведомление.
 */
export function HandOverButton({
  lead,
  name,
  primary = true,
}: {
  lead: string;
  name: string;
  primary?: boolean;
}) {
  const { t } = useTranslation("messages");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type={primary ? "primary" : "default"}
        onClick={() => {
          setOpen(true);
        }}
        aria-label={`${t("actions.handOver")}: ${name}`}
      >
        {t("actions.handOver")}
      </Button>
      {open ? (
        <HandOverDialog
          lead={lead}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function HandOverDialog({ lead, onClose }: { lead: string; onClose: () => void }) {
  const { t } = useTranslation("messages");
  const { message } = App.useApp();
  const refresh = useRefreshMessages();
  const ids = { manager: useId(), note: useId(), type: useId() };
  const managers = useListCrmLeadManagers();
  const [manager, setManager] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [type, setType] = useState<LeadRequestType | null>(null);
  const [touched, setTouched] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const items = managers.data?.items ?? [];
  const handOver = useHandOverCrmLead({
    mutation: {
      onSuccess: () => {
        const who = items.find((m) => m.id === manager)?.name ?? "";
        void message.success(t("actions.handedOver", { name: who }));
        refresh();
        onClose();
      },
      onError: (error) => {
        setFailure(actionError(t, error));
      },
    },
  });
  const noteMissing = !note.trim();
  const submit = () => {
    setTouched(true);
    if (!manager || noteMissing) return;
    setFailure(null);
    handOver.mutate({
      lead,
      data: { user_id: manager, note: note.trim(), request_type: type },
    });
  };
  return (
    <Dialog
      open
      title={t("handOver.title")}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("handOver.cancel")}
        </Button>,
        <Button key="submit" type="primary" loading={handOver.isPending} onClick={submit}>
          {t("handOver.submit")}
        </Button>,
      ]}
    >
      <div className="pf-msg-handover">
        <p className="pf-hint">{t("handOver.hint")}</p>
        <FormField
          id={ids.manager}
          label={t("handOver.manager")}
          hint={
            touched && !manager
              ? t("handOver.managerRequired")
              : managers.isError
                ? t("handOver.managersFailed")
                : managers.isSuccess && !items.length
                  ? t("handOver.noManagers")
                  : undefined
          }
        >
          <Select
            id={ids.manager}
            status={touched && !manager ? "error" : undefined}
            loading={managers.isPending}
            placeholder={t("handOver.managerPlaceholder")}
            value={manager}
            onChange={(value: string) => {
              setManager(value);
            }}
            options={items.map((m) => ({ value: m.id, label: m.name }))}
            style={{ width: "100%" }}
          />
        </FormField>
        <FormField
          id={ids.note}
          label={t("handOver.note")}
          hint={touched && noteMissing ? t("handOver.noteRequired") : undefined}
        >
          <Input.TextArea
            id={ids.note}
            aria-required
            status={touched && noteMissing ? "error" : undefined}
            rows={4}
            maxLength={2000}
            showCount
            placeholder={t("handOver.notePlaceholder")}
            value={note}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </FormField>
        <FormField id={ids.type} label={t("handOver.type")}>
          <Select
            id={ids.type}
            allowClear
            placeholder={t("handOver.typePlaceholder")}
            value={type}
            onChange={(value: LeadRequestType | undefined) => {
              setType(value ?? null);
            }}
            options={TYPES.map((value) => ({ value, label: t(`requestTypes.${value}`) }))}
            style={{ width: "100%" }}
          />
        </FormField>
        <ErrorNote message={failure} />
      </div>
    </Dialog>
  );
}

/**
 * «Передать коллеге» (LH-1): лид уже у сотрудника, он передаёт его другому менеджеру — стадия не меняется, клиент видит имя
 * нового менеджера. Одна кнопка и окно с выбором коллеги; итог — на экране после обновления.
 */
export function ReassignButton({ lead, name }: { lead: string; name: string }) {
  const { t } = useTranslation("messages");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
        aria-label={`${t("reassign.open")}: ${name}`}
      >
        {t("reassign.open")}
      </Button>
      {open ? (
        <ReassignDialog
          lead={lead}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function ReassignDialog({ lead, onClose }: { lead: string; onClose: () => void }) {
  const { t } = useTranslation("messages");
  const refresh = useRefreshMessages();
  const id = useId();
  const colleagues = useListCrmLeadColleagues();
  const [colleague, setColleague] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const items = colleagues.data?.items ?? [];
  const assign = useAssignCrmLead({
    mutation: {
      onSuccess: () => {
        refresh();
        onClose();
      },
      onError: (error) => {
        setFailure(actionError(t, error));
      },
    },
  });
  const submit = () => {
    setTouched(true);
    if (!colleague) return;
    setFailure(null);
    assign.mutate({ lead, data: { user_id: colleague } });
  };
  return (
    <Dialog
      open
      title={t("reassign.title")}
      okLabel={t("reassign.submit")}
      loading={assign.isPending}
      onOk={submit}
      onCancel={onClose}
    >
      <div className="pf-msg-handover">
        <FormField
          id={id}
          label={t("handOver.manager")}
          hint={
            touched && !colleague
              ? t("handOver.managerRequired")
              : colleagues.isError
                ? t("handOver.managersFailed")
                : colleagues.isSuccess && !items.length
                  ? t("handOver.noManagers")
                  : undefined
          }
        >
          <Select
            id={id}
            status={touched && !colleague ? "error" : undefined}
            loading={colleagues.isPending}
            placeholder={t("handOver.managerPlaceholder")}
            value={colleague}
            onChange={(value: string) => {
              setColleague(value);
            }}
            options={items.map((m) => ({ value: m.id, label: m.name }))}
            style={{ width: "100%" }}
          />
        </FormField>
        <ErrorNote message={failure} />
      </div>
    </Dialog>
  );
}
