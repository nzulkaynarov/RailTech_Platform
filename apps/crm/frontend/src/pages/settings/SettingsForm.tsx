import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Affix, Alert, App as AntApp, Button, Card, Flex, Form, Tag, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router";

import { adminKeys } from "../../api/adminQueries";
import { escalationDryRun, putSetting } from "../../api/generated/crm";
import type { DryRunResponse, EscalationSettings } from "../../api/generated/model";
import { ApiError } from "../../api/http";
import { SchemaField } from "../../components/SchemaFields";
import { type JsonSchema, normalize, withoutFields } from "../../domain/schemaForm";
import { errorPaths } from "../../domain/settingsLayout";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useUnsavedChangesPrompt } from "../../hooks/useUnsavedChangesPrompt";
import { t } from "../../i18n/ru";
import { DryRunPanel } from "./DryRunPanel";
import { TextsSection } from "./TextsSection";

type Values = Record<string, unknown>;
type Props = {
  settingKey: string;
  title: string;
  hint?: string | undefined;
  /** id заголовка раздела (для `aria-labelledby` обёртки). */
  headingId?: string;
  /** Прилипать ли шапке к верху экрана; в мастере первого запуска форм несколько — нет. */
  sticky?: boolean;
  schema: JsonSchema;
  values: Values;
  samples: Record<string, string>;
};

function useSettingMutations(
  settingKey: string,
  onSaved: () => void,
  onInvalid: (paths: string[][]) => void,
) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const [report, setReport] = useState<DryRunResponse | null>(null);
  const save = useMutation({
    mutationFn: async (body: Values) => await putSetting(settingKey, body),
    onSuccess: () => {
      onSaved();
      const section = t.settings.keys[settingKey] ?? settingKey;
      void message.success(t.settings.saved.replace("{section}", section));
      void client.invalidateQueries({ queryKey: adminKeys.settings });
    },
    onError: (error) => {
      onError(error);
      if (error instanceof ApiError) onInvalid(errorPaths(error.details));
    },
  });
  const dryRun = useMutation({
    mutationFn: async (body: Values) =>
      await escalationDryRun(body as unknown as EscalationSettings),
    onSuccess: setReport,
    onError,
  });
  return { save, dryRun, report };
}

/**
 * Шапка раздела: заголовок слева, «Сохранить» / «Отменить изменения» и тег несохранённого —
 * справа; прилипает к верху экрана (antd `Affix`), поля формы не закрывает.
 */
function SectionHeader({
  title,
  headingId,
  sticky,
  dirty,
  saving,
  onDiscard,
}: {
  title: string;
  headingId: string;
  sticky: boolean;
  dirty: boolean;
  saving: boolean;
  onDiscard: () => void;
}) {
  const header = (
    <Flex wrap gap="small" align="center" justify="space-between" className="settings-header">
      <Typography.Title level={2} id={headingId} className="section-title">
        {title}
      </Typography.Title>
      <Flex wrap gap="small" align="center">
        <span role="status">
          {dirty ? (
            <Tag color="warning">{t.settings.unsaved}</Tag>
          ) : (
            <Typography.Text type="secondary">{t.settings.allSaved}</Typography.Text>
          )}
        </span>
        {dirty ? <Button onClick={onDiscard}>{t.settings.discard}</Button> : null}
        <Button type="primary" htmlType="submit" loading={saving} disabled={!dirty}>
          {t.common.save}
        </Button>
      </Flex>
    </Flex>
  );
  return sticky ? <Affix offsetTop={0}>{header}</Affix> : header;
}

/** Форма одного раздела настроек (ключ `settings`), схема — Pydantic с бэка. */
export function SettingsForm({
  settingKey,
  title,
  hint,
  headingId = "settings-section-title",
  sticky = true,
  schema,
  values,
  samples,
}: Props) {
  const [form] = Form.useForm<Values>();
  const [dirty, setDirty] = useState(false);
  const [invalid, setInvalid] = useState<string[][]>([]);
  const { save, dryRun, report } = useSettingMutations(
    settingKey,
    () => {
      setDirty(false);
      setInvalid([]);
    },
    (paths) => {
      setInvalid(paths);
      form.setFields(paths.map((name) => ({ name, errors: [t.settingsUi.invalidField] })));
    },
  );
  useUnsavedChangesPrompt(t.settings.leaveConfirm, dirty);
  const body = () => normalize(form.getFieldsValue(true), schema, schema) as Values;

  const discard = () => {
    form.resetFields();
    setDirty(false);
  };

  return (
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
      <SectionHeader
        title={title}
        headingId={headingId}
        sticky={sticky}
        dirty={dirty}
        saving={save.isPending}
        onDiscard={discard}
      />
      {hint ? <Typography.Paragraph type="secondary">{hint}</Typography.Paragraph> : null}
      <Card size="small">
        {settingKey === "qualification" ? (
          <Alert type="info" showIcon message={t.settings.qualificationHint} className="mb-16" />
        ) : null}
        {settingKey === "texts" ? (
          <TextsSection
            schema={schema}
            samples={samples}
            saving={save.isPending}
            invalid={invalid}
          />
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
      </Card>
    </Form>
  );
}
