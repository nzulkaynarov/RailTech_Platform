import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Input, Modal, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";

import { useAuth } from "../../app/auth/useAuth";
import type { TicketSubject } from "../../shared/api/generated/model";
import { getListMyTicketsQueryKey, useCreateTicket } from "../../shared/api/generated/platform-bff";
import { rolesText } from "../help/startKinds";
import { Consequence } from "../../shared/ui/Consequence";
import { TICKET_SUBJECTS, TICKET_TEXT_MAX, ticketErrorText } from "./ticketMeta";

export interface WriteToAdminModalProps {
  open: boolean;
  onClose: () => void;
  /** Тема, выбранная заранее («Нужен доступ к разделу» на экране «Нет доступа») */
  defaultSubject?: TicketSubject;
  /** Текст-заготовка (раздел, к которому нужен доступ) */
  defaultBody?: string;
}

/**
 * «Написать администратору» (W15-H7, UX-оценка P1-4): тема из пяти, текст, страница и роль прикладываются сами.
 * Одно окно и на экране «Нет доступа», и в «Помощи». После отправки — номер обращения и куда придёт ответ.
 * Фокус держит и возвращает Modal antd; Escape и «Отмена» закрывают окно, текст при ошибке не теряется.
 */
export function WriteToAdminModal({
  open,
  onClose,
  defaultSubject,
  defaultBody,
}: WriteToAdminModalProps) {
  const { t } = useTranslation(["help", "shell"]);
  const { me } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const ids = { subject: useId(), body: useId(), bodyHint: useId(), auto: useId() };

  const [subject, setSubject] = useState<TicketSubject | undefined>(defaultSubject);
  const [body, setBody] = useState(defaultBody ?? "");
  const [touched, setTouched] = useState(false);
  // Страница фиксируется в момент открытия (окно монтируется при открытии), а не отправки.
  // Только путь без query: в query бывают номера, поиск и другие данные, которым в обращении не место.
  const [page] = useState(location.pathname);
  const [sent, setSent] = useState<string | null>(null);

  const create = useCreateTicket({
    mutation: {
      onSuccess: (ticket) => {
        setSent(ticket.number);
        void queryClient.invalidateQueries({ queryKey: getListMyTicketsQueryKey() });
      },
    },
  });

  const trimmed = body.trim();
  const subjectError = touched && !subject ? t("help:write.subjectRequired") : undefined;
  const bodyError =
    touched && trimmed === ""
      ? t("help:write.bodyRequired")
      : trimmed.length > TICKET_TEXT_MAX
        ? t("help:write.bodyTooLong")
        : undefined;

  const submit = () => {
    setTouched(true);
    if (!subject || trimmed === "" || trimmed.length > TICKET_TEXT_MAX) return;
    create.mutate({ data: { subject, body: trimmed, page } });
  };

  const close = () => {
    if (create.isPending && !sent) return;
    onClose();
  };

  const role = rolesText(me);
  const autoText = page
    ? t("help:write.auto", { page, role })
    : t("help:write.autoNoPage", { role });

  if (sent) {
    return (
      <Modal
        open={open}
        onCancel={close}
        title={t("help:write.doneTitle", { number: sent })}
        footer={[
          <Button
            key="open"
            onClick={() => {
              onClose();
              void navigate(`/help/requests/${encodeURIComponent(sent)}`);
            }}
          >
            {t("help:write.open")}
          </Button>,
          <Button key="close" type="primary" onClick={close}>
            {t("help:write.close")}
          </Button>,
        ]}
        destroyOnHidden
      >
        <p role="status" style={{ margin: 0 }}>
          {t("help:write.doneText")}
        </p>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      onCancel={close}
      title={t("help:write.title")}
      okText={create.isPending ? t("help:write.sending") : t("help:write.submit")}
      cancelText={t("help:write.cancel")}
      onOk={submit}
      okButtonProps={{ loading: create.isPending }}
      cancelButtonProps={{ disabled: create.isPending }}
      maskClosable={false}
      destroyOnHidden
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <p style={{ margin: 0 }}>{t("help:write.lead")}</p>
        {create.isError ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={ticketErrorText(t, "write", create.error)}
          />
        ) : null}
        <div>
          <label htmlFor={ids.subject} style={{ display: "block", marginBottom: 4 }}>
            {t("help:write.subject")}
          </label>
          <Select<TicketSubject>
            id={ids.subject}
            style={{ width: "100%" }}
            value={subject}
            placeholder={t("help:write.subjectPlaceholder")}
            status={subjectError ? "error" : undefined}
            aria-invalid={subjectError ? true : undefined}
            options={TICKET_SUBJECTS.map((value) => ({
              value,
              label: t(`help:ticket.subject.${value}`),
            }))}
            onChange={setSubject}
          />
          {subjectError ? (
            <div role="alert" style={{ color: "#cf1322", fontSize: 13 }}>
              {subjectError}
            </div>
          ) : null}
        </div>
        <div>
          <label htmlFor={ids.body} style={{ display: "block", marginBottom: 4 }}>
            {t("help:write.body")}
          </label>
          <Input.TextArea
            id={ids.body}
            rows={5}
            value={body}
            placeholder={t("help:write.bodyPlaceholder")}
            status={bodyError ? "error" : undefined}
            aria-invalid={bodyError ? true : undefined}
            aria-describedby={`${ids.bodyHint} ${ids.auto}`}
            onChange={(event) => {
              setBody(event.target.value);
            }}
          />
          <div id={ids.bodyHint} className="pf-hint">
            {t("help:write.bodyHint")}
          </div>
          {bodyError ? (
            <div role="alert" style={{ color: "#cf1322", fontSize: 13 }}>
              {bodyError}
            </div>
          ) : null}
        </div>
        <p id={ids.auto} className="pf-hint" style={{ margin: 0 }}>
          {autoText}
        </p>
        <Consequence
          title={t("help:write.consequenceTitle")}
          items={t("help:write.consequence", { returnObjects: true }) as string[]}
        />
      </div>
    </Modal>
  );
}
