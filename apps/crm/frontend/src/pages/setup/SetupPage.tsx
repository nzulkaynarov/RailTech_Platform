import { useInvalidateAuthStore } from "@refinedev/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, Result, Skeleton, Steps, Typography } from "antd";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";

import { useSettings } from "../../api/adminQueries";
import { createFirstAdmin } from "../../api/generated/crm";
import type { SetupAdminRequest } from "../../api/generated/model";
import { tokenStore, unwrap } from "../../api/http";
import { systemKeys, useSetupState } from "../../api/systemQueries";
import { passwordChange } from "../../app/providers/auth";
import { apiErrorField, apiErrorMessage } from "../../hooks/useApiErrorToast";
import { useDirtyForms } from "../../hooks/useDirtyForms";
import type { JsonSchema } from "../../domain/schemaForm";
import { t } from "../../i18n/ru";
import { SettingsForm } from "../settings/SettingsForm";
import "../pages.css";
import "./setup.css";

const COMPANY_SECTIONS = ["company", "business_hours"] as const;

function AdminStep({ onDone }: { onDone: () => void }) {
  const [form] = Form.useForm<SetupAdminRequest>();
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: async (body: SetupAdminRequest) => unwrap(await createFirstAdmin(body)),
    onSuccess: (data) => {
      tokenStore.set(data.access_token);
      passwordChange.required = data.must_change_password;
      onDone();
    },
    onError: (err) => {
      const field = apiErrorField(err);
      const message = apiErrorMessage(err);
      if (field) form.setFields([{ name: field as keyof SetupAdminRequest, errors: [message] }]);
      setError(message);
    },
  });
  return (
    <>
      <Typography.Paragraph>{t.setup.intro}</Typography.Paragraph>
      {error ? <Alert type="error" showIcon message={error} className="auth-alert" /> : null}
      <Form<SetupAdminRequest>
        form={form}
        layout="vertical"
        onFinish={(values) => {
          setError(null);
          create.mutate(values);
        }}
      >
        <Form.Item name="code" label={t.setup.code} rules={[{ required: true }]}>
          <Input autoComplete="one-time-code" autoFocus spellCheck={false} />
        </Form.Item>
        <Form.Item name="full_name" label={t.setup.fullName} rules={[{ required: true }]}>
          <Input autoComplete="name" />
        </Form.Item>
        <Form.Item name="email" label={t.setup.email} rules={[{ required: true, type: "email" }]}>
          <Input autoComplete="username" />
        </Form.Item>
        <Form.Item
          name="password"
          label={t.setup.password}
          extra={t.setup.passwordHint}
          rules={[{ required: true, min: 8 }]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={create.isPending}>
          {t.setup.createAdmin}
        </Button>
      </Form>
    </>
  );
}

function CompanyStep({ onDone }: { onDone: () => void }) {
  const query = useSettings();
  const onDirtyChange = useDirtyForms();
  const data = query.data;
  if (!data) return <Skeleton active />;
  return (
    <>
      <Typography.Paragraph>{t.setup.companyIntro}</Typography.Paragraph>
      {COMPANY_SECTIONS.map((key) => (
        <section key={key} aria-labelledby={`setup-${key}`} className="setup-section">
          <SettingsForm
            settingKey={key}
            title={t.settings.keys[key] ?? key}
            headingId={`setup-${key}`}
            sticky={false}
            schema={data.schemas[key] as JsonSchema}
            values={data.values[key] ?? {}}
            samples={t.settings.samples}
            onDirtyChange={onDirtyChange}
          />
        </section>
      ))}
      <Button type="primary" block onClick={onDone}>
        {t.setup.next}
      </Button>
    </>
  );
}

/**
 * Мастер первого запуска (`/setup`): пока в CRM нет администратора. Шаги: код из логов и
 * админ → компания и рабочие часы (те же формы, что в «Настройках») → главная с чек-листом.
 */
export function SetupPage() {
  const state = useSetupState();
  const navigate = useNavigate();
  const client = useQueryClient();
  const invalidateAuth = useInvalidateAuthStore();
  const [step, setStep] = useState(0);
  if (state.isLoading) return <Skeleton active />;
  if (step === 0 && state.data && !state.data.needs_setup) return <Navigate to="/login" replace />;
  const adminCreated = async () => {
    client.setQueryData(systemKeys.setupState, { needs_setup: false });
    await invalidateAuth();
    setStep(1);
  };
  const steps = [t.setup.steps.admin, t.setup.steps.company, t.setup.steps.finish];
  return (
    <main className="page-center">
      <Card className="setup-card">
        <Typography.Text type="secondary">{t.app.title}</Typography.Text>
        <Typography.Title level={1} className="page-title auth-title">
          {t.page.setup}
        </Typography.Title>
        <Steps
          current={step}
          size="small"
          responsive={false}
          className="setup-steps"
          items={steps.map((title) => ({ title }))}
        />
        {step === 0 ? <AdminStep onDone={() => void adminCreated()} /> : null}
        {step === 1 ? (
          <CompanyStep
            onDone={() => {
              setStep(2);
            }}
          />
        ) : null}
        {step === 2 ? (
          <Result
            status="success"
            title={<h2 className="result-heading">{t.setup.finishTitle}</h2>}
            subTitle={t.setup.finishText}
            extra={
              <Button type="primary" onClick={() => void navigate("/")}>
                {t.setup.open}
              </Button>
            }
          />
        ) : null}
      </Card>
    </main>
  );
}
