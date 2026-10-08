import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Card, Form, Space, Tabs } from "antd";
import { useState } from "react";

import { adminKeys, useSettings } from "../../api/adminQueries";
import { escalationDryRun, putSetting } from "../../api/generated/crm";
import type { DryRunResponse, EscalationSettings } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { SchemaField } from "../../components/SchemaFields";
import { type JsonSchema, normalize } from "../../components/schemaForm";
import { errorText, t } from "../../i18n/ru";
import { DryRunPanel } from "./DryRunPanel";

type Values = Record<string, unknown>;

function KeyForm({
  settingKey,
  schema,
  values,
  company,
}: {
  settingKey: string;
  schema: JsonSchema;
  values: Values;
  company: string;
}) {
  const [form] = Form.useForm<Values>();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const [report, setReport] = useState<DryRunResponse | null>(null);
  const onError = (e: unknown) => {
    void message.error(errorText((e as ApiError).code, (e as Error).message));
  };
  const save = useMutation({
    mutationFn: async (body: Values) => unwrap(await putSetting(settingKey, body)),
    onSuccess: () => {
      void message.success(t.common.saved);
      void client.invalidateQueries({ queryKey: adminKeys.settings });
    },
    onError,
  });
  const dryRun = useMutation({
    mutationFn: async (body: Values) =>
      unwrap(await escalationDryRun(body as unknown as EscalationSettings)),
    onSuccess: setReport,
    onError,
  });
  const body = () => normalize(form.getFieldsValue(true), schema, schema) as Values;

  return (
    <Card size="small">
      <Form
        form={form}
        layout="vertical"
        initialValues={values}
        onFinish={() => {
          save.mutate(body());
        }}
      >
        <SchemaField name={[]} schema={schema} root={schema} label="" company={company} />
        <Space wrap>
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            {t.common.save}
          </Button>
          {settingKey === "escalation" ? (
            <Button
              loading={dryRun.isPending}
              onClick={() => {
                dryRun.mutate(body());
              }}
            >
              {t.settings.dryRun}
            </Button>
          ) : null}
        </Space>
      </Form>
      {report ? <DryRunPanel report={report} /> : null}
    </Card>
  );
}

/** Настройки (admin, PLAN Фаза 5): формы по Pydantic-схемам, предпросмотр текстов, сухой прогон. */
export function SettingsPage() {
  const { data, isLoading } = useSettings();
  if (isLoading || !data) return <Card loading />;
  const name = data.values["company"]?.["name"];
  const company = typeof name === "string" ? name : "";
  return (
    <Tabs
      tabPosition="top"
      items={Object.keys(data.schemas).map((key) => ({
        key,
        label: t.settings.keys[key] ?? key,
        children: (
          <KeyForm
            settingKey={key}
            schema={data.schemas[key] as JsonSchema}
            values={data.values[key] ?? {}}
            company={company}
          />
        ),
      }))}
    />
  );
}
