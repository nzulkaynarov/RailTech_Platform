import { useQueryClient } from "@tanstack/react-query";
import { App, Form, InputNumber } from "antd";
import { useTranslation } from "react-i18next";

import type { PlatformSettings } from "../../../../shared/api/generated/model";
import {
  getGetPlatformSettingsQueryKey,
  useGetPlatformSettings,
  useUpdatePlatformSettings,
} from "../../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../../shared/lib/useFormat";
import { DefinitionList } from "../../../../shared/ui/DefinitionList";
import { QueryGate, SaveBlock, TabHeader } from "../common";
import { errorFields } from "../errors";

interface Values {
  vat_rate: string;
}

/** Платформенные настройки (ERP `system-settings`): ставка НДС — правится, курс USD→UZS — только чтение. */
export function PlatformTab() {
  const { t } = useTranslation("company");
  const query = useGetPlatformSettings();
  return (
    <div className="pf-co-body">
      <TabHeader title={t("platform.title")} hint={t("platform.hint")} />
      <QueryGate query={query}>
        {(settings) => <PlatformForm key={JSON.stringify(settings)} settings={settings} />}
      </QueryGate>
    </div>
  );
}

function PlatformForm({ settings }: { settings: PlatformSettings }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const { number, date } = useFormat();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const watched = Form.useWatch("vat_rate", form) as string | undefined;
  const changed = watched !== undefined && watched !== settings.vat_rate;
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
      initialValues={{ vat_rate: settings.vat_rate }}

      onFinish={(values) => {
        update.mutate(
          { data: { vat_rate: values.vat_rate } },
          {
            onError: (error) => {
              form.setFields(
                errorFields(error)
                  .filter((name) => name === "vat_rate")
                  .map(() => ({ name: "vat_rate" as const, errors: [t("platform.invalidVat")] })),
              );
            },
          },
        );
      }}
    >
      <div className="pf-co-grid">
        <Form.Item
          name="vat_rate"
          label={t("platform.vat")}
          extra={t("platform.vatHint")}
          rules={[{ required: true, message: t("required") }]}
        >
          <InputNumber stringMode min="0" max="100" step="0.5" style={{ width: "100%" }} />
        </Form.Item>
      </div>
      <DefinitionList
        items={[
          {
            label: t("platform.rate"),
            value:
              settings.exchange_rate_usd_uzs === null
                ? null
                : `1 USD = ${number(settings.exchange_rate_usd_uzs, { fractionDigits: 2 })} ${t("platform.currencyUzs")}`,
          },
          { label: t("platform.updated"), value: date(settings.updated_at) },
        ]}
      />
      <p className="pf-co-hint" style={{ margin: "8px 0 16px" }}>
        {t("platform.rateHint")}
      </p>
      <SaveBlock
        label={t("platform.save")}
        loading={update.isPending}
        disabled={!changed}
        error={update.error}
        consequence={[t("platform.consequence.new"), t("platform.consequence.admin")]}
      />
    </Form>
  );
}
