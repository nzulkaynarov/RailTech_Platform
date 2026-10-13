import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button, Form, Input, Modal, Select, Typography } from "antd";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { createLead } from "../../api/generated/crm";
import type { ManualLeadIn } from "../../api/generated/model";
import { invalidateKeys, queryKeys } from "../../api/queryKeys";
import { languageOptions } from "../../domain/labels";
import { apiErrorMessage } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import {
  type Duplicate,
  MANUAL_SOURCES,
  type NewLeadFormValues,
  duplicateOf,
  duplicatePath,
  leadFieldError,
  requiredContact,
  toLeadIn,
} from "./newLeadForm";

type Props = { open: boolean; onClose: () => void };

/** Ссылка на найденного лида/клиента вместо второй карточки (409 `lead_exists`/`client_exists`). */
function DuplicateNotice({ duplicate, onClose }: { duplicate: Duplicate; onClose: () => void }) {
  const label = duplicate.kind === "lead" ? t.newLead.openLead : t.newLead.openClient;
  return (
    <Alert
      type="warning"
      showIcon
      role="alert"
      message={duplicate.text}
      action={
        <Link to={duplicatePath(duplicate)} onClick={onClose}>
          <Button size="small">{label}</Button>
        </Link>
      }
    />
  );
}

/**
 * «Новый лид» во «Входящих» (M3-CRM-05): звонок, письмо, рекомендация. Создавший становится
 * ответственным, после успеха открывается карточка. Совпадение телефона/почты — не дубль,
 * а предложение открыть существующего.
 */
export function NewLeadDialog({ open, onClose }: Props) {
  const [form] = Form.useForm<NewLeadFormValues>();
  const watched = Form.useWatch<ManualLeadIn["source"] | undefined>("source", form);
  const source = watched ?? "phone";
  const [duplicate, setDuplicate] = useState<Duplicate | null>(null);
  const query = useQueryClient();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const save = useMutation({
    mutationFn: (values: NewLeadFormValues) => createLead(toLeadIn(values)),
    onSuccess: (created, values) => {
      void message.success(t.newLead.created.replace("{name}", values.name.trim()));
      void invalidateKeys(query, queryKeys.leadLists());
      onClose();
      void navigate(`/leads/${String(created.id)}`);
    },
    onError: (error) => {
      const found = duplicateOf(error);
      if (found) {
        setDuplicate(found);
        return;
      }
      const field = leadFieldError(error);
      if (field) form.setFields([field]);
      else void message.error(apiErrorMessage(error));
    },
  });
  const contact = requiredContact(source);
  // Рекомендация: хотя бы один контакт — телефон или email (у звонка/письма своё обязательное поле).
  const contactRule = {
    validator: () => {
      const phone = String(form.getFieldValue("phone") ?? "").trim();
      const email = String(form.getFieldValue("email") ?? "").trim();
      return contact !== "any" || phone || email
        ? Promise.resolve()
        : Promise.reject(new Error(t.apiReasons["contact_required"]));
    },
  };
  return (
    <Modal
      open={open}
      title={t.newLead.title}
      okText={t.newLead.create}
      cancelText={t.actions.cancel}
      confirmLoading={save.isPending}
      onOk={() => {
        form.submit();
      }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">{t.newLead.hint}</Typography.Paragraph>
      {duplicate ? <DuplicateNotice duplicate={duplicate} onClose={onClose} /> : null}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ source: "phone", language: "ru" }}
        onFinish={(values) => {
          setDuplicate(null);
          save.mutate(values);
        }}
      >
        <Form.Item name="source" label={t.newLead.source} rules={[{ required: true }]}>
          <Select
            options={MANUAL_SOURCES.map((value) => ({
              value,
              label: t.newLead.sources[value] ?? value,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="name"
          label={t.newLead.name}
          rules={[{ required: true, whitespace: true, max: 255, message: t.newLead.nameRequired }]}
        >
          <Input autoComplete="off" />
        </Form.Item>
        <Form.Item name="company" label={t.newLead.company} rules={[{ max: 255 }]}>
          <Input autoComplete="organization" />
        </Form.Item>
        <Form.Item
          name="phone"
          label={t.newLead.phone}
          extra={t.newLead.phoneHint}
          dependencies={["email", "source"]}
          rules={[
            { required: contact === "phone", whitespace: true, message: t.newLead.phoneRequired },
            { max: 32 },
            contactRule,
          ]}
        >
          <Input type="tel" inputMode="tel" />
        </Form.Item>
        <Form.Item
          name="email"
          label={t.newLead.email}
          dependencies={["phone", "source"]}
          rules={[
            { required: contact === "email", whitespace: true, message: t.newLead.emailRequired },
            { max: 255 },
            contactRule,
          ]}
        >
          <Input type="email" inputMode="email" />
        </Form.Item>
        <Form.Item name="need" label={t.newLead.need} rules={[{ max: 4000 }]}>
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="language" label={t.newLead.language}>
          <Select options={languageOptions()} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** Кнопка «Новый лид» с диалогом — показывается при праве `leads:create`. */
export function NewLeadButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="primary"
        onClick={() => {
          setOpen(true);
        }}
      >
        {t.newLead.button}
      </Button>
      <NewLeadDialog
        // Новый ключ на каждое открытие: форма и состояние «дубль найден» начинаются с чистого листа.
        key={String(open)}
        open={open}
        onClose={() => {
          setOpen(false);
        }}
      />
    </>
  );
}
