import { useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router";

import { changePassword } from "../../api/generated/crm";
import type { ApiError } from "../../api/http";
import { refreshAccess } from "../../api/http";
import { errorText, t } from "../../i18n/ru";
import { passwordChange } from "../../app/providers/auth";
import "../pages.css";

type Values = { current_password: string; new_password: string; repeat: string };

export function ChangePasswordPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (values: Values) => {
    setSaving(true);
    try {
      await changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      });
      passwordChange.required = false;
      await refreshAccess();
      await client.invalidateQueries();
      void message.success(t.auth.changed);
      void navigate("/");
    } catch (e) {
      setError(errorText((e as ApiError).code, (e as ApiError).message));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-center">
      <Card className="auth-card">
        <Typography.Title level={4}>{t.auth.changeTitle}</Typography.Title>
        <Typography.Paragraph type="secondary">{t.auth.changeHint}</Typography.Paragraph>
        {error ? <Alert type="error" showIcon message={error} className="auth-alert" /> : null}
        <Form<Values> layout="vertical" onFinish={(v) => void submit(v)}>
          <Form.Item name="current_password" label={t.auth.current} rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="new_password" label={t.auth.next} rules={[{ required: true, min: 10 }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="repeat"
            label={t.auth.repeat}
            dependencies={["new_password"]}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator: (_, value) =>
                  value === getFieldValue("new_password")
                    ? Promise.resolve()
                    : Promise.reject(new Error(t.auth.mismatch)),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={saving}>
            {t.auth.save}
          </Button>
        </Form>
      </Card>
    </div>
  );
}
