import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Form, Input, InputNumber, Radio, Select } from "antd";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  DocumentKind,
  NumberingResetPeriod,
  NumberingScheme,
  NumberingUpdate,
} from "../../../../shared/api/generated/model";
import {
  getGetNumberingSchemeQueryKey,
  useGetNumberingScheme,
  usePreviewNumbering,
  useUpdateNumberingScheme,
} from "../../../../shared/api/generated/platform-bff";
import { QueryGate, SaveBlock, TabHeader, ReadOnlyFence } from "../common";
import { changedFields, isEmptyObject } from "../diff";
import { errorFields } from "../errors";

const KINDS: DocumentKind[] = ["quote", "contract", "invoice", "act", "letter"];
const RESET: NumberingResetPeriod[] = ["never", "yearly", "monthly"];
const PRESETS = [
  { id: "brand", pattern: "{prefix}{type}-{YYYY}-{seq}" },
  { id: "slash", pattern: "{type}/{YYYY}/{seq}" },
  { id: "compact", pattern: "{type}-{seq}" },
] as const;

interface Values {
  prefix: string;
  pattern: string;
  padding: number;
  reset_period: NumberingResetPeriod;
  start_value: number;
  type_labels: Record<string, string>;
}

const toValues = (s: NumberingScheme): Values => ({
  prefix: s.prefix,
  pattern: s.pattern,
  padding: s.padding,
  reset_period: s.reset_period,
  start_value: s.start_value,
  type_labels: Object.fromEntries(KINDS.map((k) => [k, s.type_labels[k] ?? ""])),
});

const presetOf = (pattern: string) => PRESETS.find((p) => p.pattern === pattern)?.id ?? "custom";

/** Нумерация документов (ERP `crm/numbering-scheme`): маска, счётчик, сброс, обозначения и образец номера. */
export function NumberingTab() {
  const { t } = useTranslation("company");
  const query = useGetNumberingScheme();
  return (
    <div className="pf-co-body">
      <TabHeader title={t("numbering.title")} hint={t("numbering.hint")} />
      <ReadOnlyFence>
        <QueryGate query={query}>
          {(scheme) => <NumberingForm key={JSON.stringify(scheme)} scheme={scheme} />}
        </QueryGate>
      </ReadOnlyFence>
    </div>
  );
}

function NumberingForm({ scheme }: { scheme: NumberingScheme }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const initial = useMemo(() => toValues(scheme), [scheme]);
  const watched = Form.useWatch([], form);
  const values: Values = { ...initial, ...watched };
  const changed = changedFields(initial, watched);
  const maskOk = values.pattern.trim() !== "" && values.pattern.includes("{seq}");

  const update = useUpdateNumberingScheme({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetNumberingSchemeQueryKey(), next);
        void message.success(t("numbering.saved"));
      },
    },
  });

  // Образец номера — «сухой прогон» ERP по черновику: счётчики не меняются.
  const preview = usePreviewNumbering();
  const { mutate: requestPreview } = preview;
  const draftKey = JSON.stringify(values);
  useEffect(() => {
    const draft = JSON.parse(draftKey) as Values;
    if (!draft.pattern.includes("{seq}")) return;
    const timer = window.setTimeout(() => {
      requestPreview({
        data: {
          pattern: draft.pattern,
          padding: draft.padding,
          reset_period: draft.reset_period,
          start_value: draft.start_value,
          prefix: draft.prefix.trim(),
          type_labels: draft.type_labels,
        },
      });
    }, 350);
    return () => {
      window.clearTimeout(timer);
    };
  }, [draftKey, requestPreview]);

  const submit = () => {
    const data: NumberingUpdate = {
      ...changed,
      ...(changed.prefix !== undefined ? { prefix: changed.prefix.trim() } : {}),
    };
    // Обозначения уходят целиком: ERP заменяет их набором, а не по одному.
    if (changed.type_labels) data.type_labels = values.type_labels;
    update.mutate(
      { data },
      {
        onError: (error) => {
          form.setFields(
            errorFields(error)
              .filter((name) => name in initial)
              .map((name) => ({
                name: name as keyof Values,
                errors: [t(name === "pattern" ? "numbering.maskInvalid" : "numbering.prefixTaken")],
              })),
          );
        },
      },
    );
  };

  return (
    <div className="pf-co-split">
      <Form<Values> form={form} layout="vertical" initialValues={initial} onFinish={submit}>
        <Form.Item
          name="prefix"
          label={t("numbering.prefix")}
          extra={t("numbering.prefixHint")}
          rules={[{ pattern: /^[A-Za-z0-9_-]*$/, message: t("numbering.prefixInvalid") }]}
        >
          <Input maxLength={16} className="pf-co-mono" autoComplete="off" />
        </Form.Item>
        {values.prefix.trim() === "" ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={t("numbering.prefixlessBanner")}
          />
        ) : null}
        <Form.Item label={t("numbering.format")} style={{ marginBottom: 8 }}>
          <Radio.Group
            aria-label={t("numbering.format")}
            value={presetOf(values.pattern)}
            onChange={(event) => {
              const preset = PRESETS.find((p) => p.id === event.target.value);
              if (preset) form.setFieldValue("pattern", preset.pattern);
            }}
            style={{ display: "flex", flexDirection: "column", gap: 4 }}
          >
            {PRESETS.map((preset) => (
              <Radio key={preset.id} value={preset.id}>
                {t(`numbering.presets.${preset.id}`)}{" "}
                <span className="pf-co-hint pf-co-mono">{preset.pattern}</span>
              </Radio>
            ))}
            <Radio value="custom">{t("numbering.presets.custom")}</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item
          name="pattern"
          label={t("numbering.mask")}
          extra={t("numbering.maskHint")}
          validateStatus={maskOk ? undefined : "error"}
          help={maskOk ? undefined : t("numbering.maskInvalid")}
        >
          <Input className="pf-co-mono" autoComplete="off" maxLength={100} />
        </Form.Item>
        <div className="pf-co-grid">
          <Form.Item
            name="padding"
            label={t("numbering.padding")}
            extra={t("numbering.paddingHint")}
          >
            <InputNumber min={1} max={10} precision={0} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="reset_period" label={t("numbering.reset")}>
            <Select
              options={RESET.map((value) => ({ value, label: t(`numbering.resets.${value}`) }))}
            />
          </Form.Item>
          <Form.Item
            name="start_value"
            label={t("numbering.start")}
            extra={t("numbering.startHint")}
          >
            <InputNumber min={0} precision={0} style={{ width: "100%" }} />
          </Form.Item>
        </div>
        <fieldset className="pf-co-fieldset">
          <legend className="pf-co-legend">{t("numbering.labelsTitle")}</legend>
          <p className="pf-co-hint">{t("numbering.labelsHint")}</p>
          <div className="pf-co-grid">
            {KINDS.map((kind) => (
              <Form.Item
                key={kind}
                name={["type_labels", kind]}
                label={t(`kinds.${kind}`)}
                style={{ marginBottom: 12 }}
              >
                <Input maxLength={16} autoComplete="off" />
              </Form.Item>
            ))}
          </div>
        </fieldset>
        <SaveBlock
          label={t("numbering.save")}
          loading={update.isPending}
          disabled={isEmptyObject(changed) || !maskOk}
          error={update.error}
          consequence={[
            t("numbering.consequence.future"),
            t("numbering.consequence.issued"),
            ...(values.prefix.trim() === "" ? [t("numbering.consequence.noPrefix")] : []),
          ]}
        />
      </Form>
      <div className="pf-co-panel">
        <h3 className="pf-co-title">{t("numbering.previewTitle")}</h3>
        {maskOk ? (
          <ul
            className="pf-co-numbers"
            aria-label={t("numbering.previewTitle")}
            aria-live="polite"
            aria-busy={preview.isPending}
          >
            {(preview.data?.items ?? []).map((row) => (
              <li key={row.kind}>
                <span>{t(`kinds.${row.kind}`)}</span>
                <b>{row.number}</b>
              </li>
            ))}
          </ul>
        ) : (
          <p className="pf-co-hint">{t("numbering.previewUnavailable")}</p>
        )}
        <p className="pf-co-hint">{t("numbering.previewHint")}</p>
      </div>
    </div>
  );
}
