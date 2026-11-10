import { App, Button, Form, Input, Modal } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { SigningAuthorityDetail } from "../../../shared/api/generated/model";
import { useRevokeSigningAuthority } from "../../../shared/api/generated/platform-bff";

interface Values {
  reason: string;
}

/** Отзыв полномочия: причина обязательна, блок «Что произойдёт» (необратимое действие, CONVENTIONS §2 п. 8). */
export function RevokeModal({
  authority,
  onClose,
  onRevoked,
}: {
  authority: SigningAuthorityDetail;
  onClose: () => void;
  onRevoked: (saved: SigningAuthorityDetail) => void;
}) {
  const { t } = useTranslation("signing");
  const { message } = App.useApp();
  const formId = useId();
  const [form] = Form.useForm<Values>();
  const revoke = useRevokeSigningAuthority();
  const failed = revoke.error;
  const text =
    failed instanceof ApiError && failed.details["reason"] === "revoked"
      ? t("errors.revoked")
      : t("errors.DEFAULT");
  return (
    <Modal
      open
      width={480}
      title={t("revoke.title", { name: authority.holder.name })}
      onCancel={onClose}
      destroyOnHidden
      maskClosable={false}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("form.cancel")}
        </Button>,
        <Button
          key="ok"
          type="primary"
          danger
          htmlType="submit"
          form={formId}
          loading={revoke.isPending}
        >
          {t("revoke.ok")}
        </Button>,
      ]}
    >
      <Form<Values>
        id={formId}
        form={form}
        layout="vertical"
        onFinish={(values) => {
          revoke.mutate(
            { id: authority.id, data: { reason: values.reason.trim() } },
            {
              onSuccess: onRevoked,
              onError: () => {
                void message.error(text);
              },
            },
          );
        }}
      >
        <Form.Item
          name="reason"
          label={t("revoke.reason")}
          extra={t("revoke.reasonHint")}
          rules={[
            { required: true, whitespace: true, min: 3, message: t("revoke.reasonRequired") },
          ]}
        >
          <Input.TextArea maxLength={1000} autoSize={{ minRows: 2, maxRows: 5 }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
