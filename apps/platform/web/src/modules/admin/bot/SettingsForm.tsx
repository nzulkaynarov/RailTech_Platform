import { Alert, App, Button, Card, Form } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useDryRunEscalation, useSaveBotSetting } from "../../../shared/api/generated/platform-bff";
import type { EscalationDryRun } from "../../../shared/api/generated/model";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { UnsavedGuard } from "../../../shared/ui/UnsavedGuard";
import { DryRunPanel } from "./DryRunPanel";
import { botErrorText, invalidPaths } from "./errors";
import { useRefreshBot } from "./refresh";
import { SchemaField } from "./SchemaField";
import { type JsonSchema, normalize, withoutFields } from "./schemaForm";
import { TextsSection } from "./TextsSection";

type Values = Record<string, unknown>;

interface Props {
  settingKey: string;
  title: string;
  schema: JsonSchema;
  values: Values;
  samples: Record<string, string>;
  editable: boolean;
  /** Раздел сохранён и перечитан: экран пересоздаёт форму с новыми значениями. */
  onSaved: () => void;
}

/** Поля, которые правятся на другом экране («Внешние интеграции») и здесь не показываются. */
const HIDDEN: Record<string, readonly string[]> = { notifications: ["channel_id"] };

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function DryRun({ body, disabled }: { body: () => Values; disabled: boolean }) {
  const { t } = useTranslation("bot");
  const [report, setReport] = useState<EscalationDryRun | null>(null);
  const run = useDryRunEscalation({ mutation: { onSuccess: setReport } });
  return (
    <section className="pf-bot-dryrun-box" aria-labelledby="pf-bot-dryrun-title">
      <h3 className="pf-bot-subtitle" id="pf-bot-dryrun-title">
        {t("dryRun.title")}
      </h3>
      <p className="pf-fp-sub">{t("dryRun.hint")}</p>
      <Consequence items={[t("dryRun.step1"), t("dryRun.step2"), t("dryRun.step3")]} />
      <div className="pf-fp-row">
        <Button
          loading={run.isPending}
          disabled={disabled}
          onClick={() => {
            run.mutate({ data: body() });
          }}
        >
          {t("dryRun.button")}
        </Button>
      </div>
      <ErrorNote message={run.isError ? botErrorText(t, run.error) : null} />
      {report ? <DryRunPanel report={report} /> : null}
    </section>
  );
}

/** Форма одного раздела настроек бота по схеме CRM: «Что произойдёт», сохранение, отмена, пробный прогон правил передачи. */
export function SettingsForm({
  settingKey,
  title,
  schema,
  values,
  samples,
  editable,
  onSaved,
}: Props) {
  const { t } = useTranslation(["bot", "kb"]);
  const [form] = Form.useForm<Values>();
  const refresh = useRefreshBot();
  const { message } = App.useApp();
  const baseline = useMemo(() => normalize(values, schema, schema), [values, schema]);
  const [dirty, setDirty] = useState(false);
  const [invalid, setInvalid] = useState<string[][]>([]);

  const body = () => normalize(form.getFieldsValue(true), schema, schema) as Values;
  const save = useSaveBotSetting({
    mutation: {
      onSuccess: async () => {
        setInvalid([]);
        await refresh();
        setDirty(false);
        void message.success(t("bot:form.saved", { section: title }));
        onSaved();
      },
      onError: (error) => {
        const paths = invalidPaths(error);
        setInvalid(paths);
        form.setFields(paths.map((name) => ({ name, errors: [t("bot:form.invalidField")] })));
      },
    },
  });

  const visible = HIDDEN[settingKey] ? withoutFields(schema, HIDDEN[settingKey]) : schema;

  return (
    <Form
      form={form}
      layout="vertical"
      className="pf-bot-form"
      disabled={!editable}
      initialValues={values}
      onValuesChange={() => {
        setDirty(!same(body(), baseline));
      }}
      onFinish={() => {
        save.mutate({ key: settingKey, data: body() });
      }}
    >
      <UnsavedGuard when={dirty} busy={save.isPending} />
      <div className="pf-bot-form-head">
        <h2 className="pf-bot-section-title" id="pf-bot-section-title">
          {title}
        </h2>
        {editable ? (
          <div className="pf-bot-form-actions">
            <span role="status">
              {dirty ? (
                <StatusTag tone="gold">{t("bot:form.unsaved")}</StatusTag>
              ) : (
                <span className="pf-hint">{t("bot:form.allSaved")}</span>
              )}
            </span>
            {dirty ? (
              <Button
                onClick={() => {
                  form.resetFields();
                  setDirty(false);
                  setInvalid([]);
                }}
              >
                {t("bot:form.discard")}
              </Button>
            ) : null}
            <Button type="primary" htmlType="submit" loading={save.isPending} disabled={!dirty}>
              {t("bot:form.save")}
            </Button>
          </div>
        ) : null}
      </div>
      {t(`bot:sectionHints.${settingKey}`, { defaultValue: "" }) ? (
        <p className="pf-fp-sub">{t(`bot:sectionHints.${settingKey}`)}</p>
      ) : null}
      {editable ? (
        <Consequence
          items={[
            t("bot:form.step1", { section: title }),
            t("bot:form.step2"),
            t("bot:form.step3"),
          ]}
        />
      ) : null}
      <ErrorNote message={save.isError ? botErrorText(t, save.error) : null} />
      <Card size="small">
        {settingKey === "qualification" ? (
          <Alert
            type="info"
            showIcon
            className="pf-bot-alert"
            message={t("bot:qualificationHint")}
          />
        ) : null}
        {settingKey === "notifications" ? (
          <Alert
            type="info"
            showIcon
            className="pf-bot-alert"
            message={t("bot:channelMoved")}
            action={
              <Link className="pf-focusable" to="/admin/bot?part=connection">
                {t("bot:openIntegrations")}
              </Link>
            }
          />
        ) : null}
        {settingKey === "texts" ? (
          <TextsSection
            schema={schema}
            samples={samples}
            saving={save.isPending}
            invalid={invalid}
            editable={editable}
          />
        ) : (
          <SchemaField name={[]} schema={visible} root={schema} label="" samples={samples} />
        )}
      </Card>
      {settingKey === "escalation" && editable ? (
        <DryRun body={body} disabled={save.isPending} />
      ) : null}
    </Form>
  );
}
