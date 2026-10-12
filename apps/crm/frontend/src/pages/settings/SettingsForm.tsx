import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Badge, Button, Card, Flex, Form, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router";

import { adminKeys } from "../../api/adminQueries";
import { escalationDryRun, putSetting } from "../../api/generated/crm";
import type { DryRunResponse, EscalationSettings } from "../../api/generated/model";
import { unwrap } from "../../api/http";
import { SchemaField } from "../../components/SchemaFields";
import { type JsonSchema, normalize, withoutFields } from "../../domain/schemaForm";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useUnsavedChangesPrompt } from "../../hooks/useUnsavedChangesPrompt";
import { t } from "../../i18n/ru";
import { DryRunPanel } from "./DryRunPanel";
import { TextsSection } from "./TextsSection";

type Values = Record<string, unknown>;
type Props = {
  settingKey: string;
  schema: JsonSchema;
  values: Values;
  samples: Record<string, string>;
};

function useSettingMutations(settingKey: string, onSaved: () => void) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const [report, setReport] = useState<DryRunResponse | null>(null);
  const save = useMutation({
    mutationFn: async (body: Values) => unwrap(await putSetting(settingKey, body)),
    onSuccess: () => {
      onSaved();
      const section = t.settings.keys[settingKey] ?? settingKey;
      void message.success(t.settings.saved.replace("{section}", section));
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
  return { save, dryRun, report };
}

/** Липкая панель внизу: «Сохранить», «Отменить изменения» и индикатор несохранённого. */
function SaveBar({
  dirty,
  saving,
  onDiscard,
}: {
  dirty: boolean;
  saving: boolean;
  onDiscard: () => void;
}) {
  return (
    <Flex wrap gap="small" align="center" className="settings-savebar">
      <Button type="primary" htmlType="submit" loading={saving} disabled={!dirty}>
        {t.common.save}
      </Button>
      {dirty ? <Button onClick={onDiscard}>{t.settings.discard}</Button> : null}
      <Typography.Text type={dirty ? "warning" : "secondary"} role="status">
        {dirty ? <Badge status="warning" text={t.settings.unsaved} /> : t.settings.allSaved}
      </Typography.Text>
    </Flex>
  );
}

/** Форма одного раздела настроек (ключ `settings`), схема — Pydantic с бэка. */
export function SettingsForm({ settingKey, schema, values, samples }: Props) {
  const [form] = Form.useForm<Values>();
  const [dirty, setDirty] = useState(false);
  const { save, dryRun, report } = useSettingMutations(settingKey, () => {
    setDirty(false);
  });
  useUnsavedChangesPrompt(t.settings.leaveConfirm, dirty);
  const body = () => normalize(form.getFieldsValue(true), schema, schema) as Values;

  return (
    <Card size="small">
      <Form
        form={form}
        layout="vertical"
        className="settings-form"
        initialValues={values}
        onValuesChange={() => {
          setDirty(true);
        }}
        onFinish={() => {
          save.mutate(body());
        }}
      >
        {settingKey === "qualification" ? (
          <Alert type="info" showIcon message={t.settings.qualificationHint} className="mb-16" />
        ) : null}
        {settingKey === "texts" ? (
          <TextsSection schema={schema} samples={samples} />
        ) : (
          <>
            {settingKey === "notifications" ? (
              <Alert
                type="info"
                showIcon
                className="mb-16"
                message={t.settingsUi.channelMoved}
                action={<Link to="/integrations">{t.settingsUi.openIntegrations}</Link>}
              />
            ) : null}
            <SchemaField
              name={[]}
              schema={
                settingKey === "notifications" ? withoutFields(schema, ["channel_id"]) : schema
              }
              root={schema}
              label=""
              samples={samples}
            />
          </>
        )}
        {settingKey === "escalation" ? (
          <Flex vertical gap="small" align="start" className="mb-16">
            <Button
              loading={dryRun.isPending}
              onClick={() => {
                dryRun.mutate(body());
              }}
            >
              {t.settings.dryRun}
            </Button>
            <Typography.Text type="secondary">{t.settings.dryRunHint}</Typography.Text>
            {report ? <DryRunPanel report={report} /> : null}
          </Flex>
        ) : null}
        <SaveBar
          dirty={dirty}
          saving={save.isPending}
          onDiscard={() => {
            form.resetFields();
            setDirty(false);
          }}
        />
      </Form>
    </Card>
  );
}
