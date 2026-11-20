import { useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, InputNumber } from "antd";
import { useTranslation } from "react-i18next";

import type { PlatformSettings } from "../../../../shared/api/generated/model";
import {
  getGetPlatformSettingsQueryKey,
  useGetPlatformSettings,
  useUpdatePlatformSettings,
} from "../../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../../shared/lib/useFormat";
import { DefinitionList } from "../../../../shared/ui/DefinitionList";
import { QueryGate, SaveBlock, TabHeader, ReadOnlyFence } from "../common";
import { errorFields } from "../errors";
import { FxRateSection } from "./FxRateSection";
import { UnitLabel } from "../../../../shared/ui/UnitLabel";
import { unitOf } from "../../../../shared/lib/unit";

interface Values {
  vat_rate: string;
  support_email: string;
}

/** Платформенные настройки ERP: ставка НДС и адрес поддержки в письмах клиентам (`system-settings`, СЦ-3) и курс USD→UZS с ручным вводом на дату (`FxRateSection`). */
export function PlatformTab() {
  const { t } = useTranslation("company");
  const query = useGetPlatformSettings();
  return (
    <div className="pf-co-body">
      <TabHeader title={t("platform.title")} hint={t("platform.hint")} />
      <ReadOnlyFence>
        <QueryGate query={query}>
          {(settings) => <PlatformForm key={JSON.stringify(settings)} settings={settings} />}
        </QueryGate>
      </ReadOnlyFence>
      <FxRateSection />
    </div>
  );
}

function PlatformForm({ settings }: { settings: PlatformSettings }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const { date } = useFormat();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const watched = Form.useWatch([], form) as Partial<Values> | undefined;
  // «12» и «12.00» — одна ставка: сравниваем числа, иначе сохранение адреса отправит и ставку
  const vatChanged =
    watched?.vat_rate !== undefined && Number(watched.vat_rate) !== Number(settings.vat_rate);
  const supportChanged =
    watched?.support_email !== undefined && watched.support_email.trim() !== settings.support_email;
  const changed = vatChanged || supportChanged;
  const update = useUpdatePlatformSettings({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetPlatformSettingsQueryKey(), next);
        void message.success(t("saved"));
      },
    },
  });
  return (
    <Form<Values>
      form={form}
      layout="vertical"
      initialValues={{ vat_rate: settings.vat_rate, support_email: settings.support_email }}

      onFinish={(values) => {
        update.mutate(
          {
            data: {
              ...(vatChanged ? { vat_rate: values.vat_rate } : {}),
              ...(supportChanged ? { support_email: values.support_email.trim() } : {}),
            },
          },
          {
            onError: (error) => {
              const failed = errorFields(error);
              form.setFields([
                ...(failed.includes("vat_rate")
                  ? [{ name: "vat_rate" as const, errors: [t("platform.invalidVat")] }]
                  : []),
                ...(failed.includes("support_email")
                  ? [{ name: "support_email" as const, errors: [t("platform.invalidSupport")] }]
                  : []),
              ]);
            },
          },
        );
      }}
    >
      <div className="pf-co-grid">
        <Form.Item
          name="vat_rate"
          label={<UnitLabel label={t("platform.vat")} />}
          extra={t("platform.vatHint")}
          rules={[{ required: true, message: t("required") }]}
        >
          <InputNumber
            suffix={unitOf(t("platform.vat"))}
            stringMode
            min="0"
            max="100"
            step="0.5"
            style={{ width: "100%" }}
          />
        </Form.Item>
        <Form.Item
          name="support_email"
          label={t("platform.support")}
          extra={t("platform.supportHint")}
          rules={[
            { required: Boolean(settings.support_email), message: t("required") },
            { type: "email", message: t("platform.invalidSupport") },
          ]}
        >
          <Input type="email" autoComplete="off" placeholder="support@company.uz" />
        </Form.Item>
      </div>
      <DefinitionList
        items={[{ label: t("platform.updated"), value: date(settings.updated_at) }]}
      />
      <SaveBlock
        label={t("platform.save")}
        loading={update.isPending}
        disabled={!changed}
        error={update.error}
        note={t("platform.note")}
        onDiscard={() => {
          form.resetFields();
          update.reset();
        }}
      />
    </Form>
  );
}
