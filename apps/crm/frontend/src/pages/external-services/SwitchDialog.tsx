import { Alert, Form, Input, Modal, Typography } from "antd";
import { useState } from "react";

import type { ExternalServiceOut } from "../../api/generated/model";
import { t } from "../../i18n/ru";

type Props = {
  service: ExternalServiceOut;
  /** true — выключаем, false — включаем обратно. */
  disabling: boolean;
  saving: boolean;
  onCancel: () => void;
  onSubmit: (password: string, reason: string | null) => void;
};

/** Выключатель сервиса (ADR-0024): что произойдёт, причина и подтверждение паролем админа. */
export function SwitchDialog({ service, disabling, saving, onCancel, onSubmit }: Props) {
  const s = t.externalServices.switch;
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const title = (disabling ? s.disableTitle : s.enableTitle).replace("{title}", service.title);
  return (
    <Modal
      open
      title={title}
      onCancel={onCancel}
      destroyOnHidden
      okText={disabling ? s.confirmDisable : s.confirmEnable}
      cancelText={s.cancel}
      okButtonProps={{ danger: disabling, disabled: !password, loading: saving }}
      onOk={() => {
        onSubmit(password, disabling && reason.trim() ? reason.trim() : null);
      }}
    >
      <Form layout="vertical" component="div">
        <Alert
          type={disabling ? "warning" : "info"}
          showIcon
          className="mb-16"
          message={disabling ? service.switch?.effect : s.enableText}
        />
        {disabling ? (
          <Form.Item label={s.reasonLabel} htmlFor="switch-reason">
            <Input.TextArea
              id="switch-reason"
              value={reason}
              maxLength={200}
              autoSize={{ minRows: 2, maxRows: 4 }}
              onChange={(e) => {
                setReason(e.target.value);
              }}
            />
          </Form.Item>
        ) : null}
        <Form.Item
          label={s.password}
          htmlFor="switch-password"
          extra={<Typography.Text type="secondary">{s.passwordHint}</Typography.Text>}
        >
          <Input.Password
            id="switch-password"
            value={password}
            autoComplete="current-password"
            onChange={(e) => {
              setPassword(e.target.value);
            }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
