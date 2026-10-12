import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Checkbox, Form, Input, Modal } from "antd";
import { useEffect } from "react";

import { adminKeys } from "../../api/adminQueries";
import { createClientContact, updateClientContact } from "../../api/generated/crm";
import type { ContactOut } from "../../api/generated/model";
import { apiErrorMessage } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import {
  type ContactFormValues,
  contactFieldError,
  toContactIn,
  toFormValues,
} from "./contactForm";

type Props = {
  clientId: number;
  /** `null` — новый контакт; объект — правка. */
  contact: ContactOut | null;
  open: boolean;
  onClose: () => void;
};

/** Добавление и правка контакта; ошибка телефона/email подсвечивает поле формы. */
export function ContactDialog({ clientId, contact, open, onClose }: Props) {
  const [form] = Form.useForm<ContactFormValues>();
  const query = useQueryClient();
  const { message } = AntApp.useApp();
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (contact) form.setFieldsValue(toFormValues(contact));
  }, [open, contact, form]);
  const save = useMutation({
    mutationFn: async (values: ContactFormValues) => {
      const body = toContactIn(values, contact?.telegram_identity_id);
      if (contact) return await updateClientContact(clientId, contact.id, body);
      return await createClientContact(clientId, body);
    },
    onSuccess: (_, values) => {
      const text = contact ? t.contacts.saved : t.contacts.added;
      void message.success(text.replace("{name}", values.full_name.trim()));
      void query.invalidateQueries({ queryKey: adminKeys.clientContacts(clientId) });
      onClose();
    },
    onError: (error) => {
      const field = contactFieldError(error);
      if (field) form.setFields([field]);
      else void message.error(apiErrorMessage(error));
    },
  });
  return (
    <Modal
      open={open}
      title={contact ? t.contacts.edit : t.contacts.add}
      okText={t.common.save}
      cancelText={t.actions.cancel}
      confirmLoading={save.isPending}
      onOk={() => {
        form.submit();
      }}
      onCancel={onClose}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(values) => {
          save.mutate(values);
        }}
      >
        <Form.Item
          name="full_name"
          label={t.contacts.fullName}
          rules={[{ required: true, whitespace: true, max: 255 }]}
        >
          <Input autoComplete="off" />
        </Form.Item>
        <Form.Item name="position" label={t.contacts.position} rules={[{ max: 255 }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="phone"
          label={t.contacts.phone}
          extra={t.contacts.phoneHint}
          rules={[{ max: 32 }]}
        >
          <Input type="tel" inputMode="tel" />
        </Form.Item>
        <Form.Item name="email" label={t.contacts.email} rules={[{ max: 255 }]}>
          <Input type="email" inputMode="email" />
        </Form.Item>
        <Form.Item name="note" label={t.contacts.note} rules={[{ max: 2000 }]}>
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="is_primary" valuePropName="checked" extra={t.contacts.primaryHint}>
          <Checkbox>{t.contacts.primary}</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  );
}
