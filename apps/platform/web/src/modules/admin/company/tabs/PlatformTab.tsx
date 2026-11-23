import { useQueryClient } from "@tanstack/react-query";
import { App, Form, Input } from "antd";
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

interface Values {
  support_email: string;
}

/** Курсы валют к суму: курс на сегодня и ручной ввод на дату (`FxRateSection`). Адрес поддержки — на «Реквизитах» (`SupportAddress`, ЕВ-2а). */
export function PlatformTab() {
  const { t } = useTranslation("company");
  return (
    <div className="pf-co-body">
      <TabHeader title={t("platform.title")} hint={t("platform.hint")} />
      <FxRateSection />
    </div>
  );
}

/** Контакт компании: адрес поддержки в письмах клиентам (`system-settings`, СЦ-3). Живёт на странице «Реквизиты и бланк» (ЕВ-2а, отчёт §8.2 п. 12). */
export function SupportAddress() {
  const { t } = useTranslation("company");
  const query = useGetPlatformSettings();
  return (
    <div className="pf-co-body">
      <TabHeader title={t("platform.supportTitle")} hint={t("platform.supportHint")} />
      <ReadOnlyFence>
        <QueryGate query={query}>
          {(settings) => <PlatformForm key={JSON.stringify(settings)} settings={settings} />}
        </QueryGate>
      </ReadOnlyFence>
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
  // Ставка НДС здесь не редактируется: расчёт читает только «Ставку НДС в новом КП» (`default_vat_rate`)
  const changed =
    watched?.support_email !== undefined && watched.support_email.trim() !== settings.support_email;
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
      initialValues={{ support_email: settings.support_email }}

      onFinish={(values) => {
        update.mutate(
          {
            data: {
              support_email: values.support_email.trim(),
            },
          },
          {
            onError: (error) => {
              const failed = errorFields(error);
              form.setFields([
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
          name="support_email"
          label={t("platform.support")}
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
        onDiscard={() => {
          form.resetFields();
          update.reset();
        }}
      />
    </Form>
  );
}
