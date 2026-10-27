import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input } from "antd";
import { useTranslation } from "react-i18next";

import { lines } from "../../../features/first-run/lines";
import { ApiError } from "../../../shared/api/errors";
import type { SetupChecklist, SetupCompanyIn } from "../../../shared/api/generated/model";
import {
  getGetSetupChecklistQueryKey,
  useCreateOwnCompany,
} from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";

interface Values {
  name: string;
  inn?: string;
  legal_address?: string;
  phone?: string;
  email?: string;
}

const FIELDS = ["name", "inn", "legal_address", "phone", "email"] as const;

function errorText(t: ReturnType<typeof useTranslation>["t"], error: unknown): string {
  const base = "admin.setup.companyErrors.";
  if (error instanceof ApiError) {
    const key = `${base}${error.code}`;
    if (
      [
        "OWN_COMPANY_ALREADY_EXISTS",
        "FORBIDDEN",
        "BACKEND_UNAVAILABLE",
        "VALIDATION_FAILED",
      ].includes(error.code)
    ) {
      return t(key);
    }
  }
  return t(`${base}default`);
}

/**
 * Шаг «Ваша компания» (ERP `setup/status`, `setup/company`, W13-A4): форма, пока своей компании нет; иначе статус словами.
 * ERP без ответа (доступ новому администратору выдаётся с задержкой) — «Проверить снова», а не тупик. Блок «Что
 * произойдёт» стоит над главной кнопкой.
 */
export function CompanyStep({
  company,
  onRetry,
  retrying,
}: {
  company: SetupChecklist["company"];
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const create = useCreateOwnCompany({
    mutation: {
      onSuccess: (created) => {
        void message.success(t("admin.setup.companyCreated", { name: created.name }));
        void queryClient.invalidateQueries({ queryKey: getGetSetupChecklistQueryKey() });
      },
      onError: (error) => {
        if (!(error instanceof ApiError) || error.code !== "VALIDATION_FAILED") return;
        const fields = error.details["fields"];
        const messages = error.details["messages"];
        if (!Array.isArray(fields)) return;
        form.setFields(
          fields
            .filter((name): name is (typeof FIELDS)[number] =>
              FIELDS.includes(name as (typeof FIELDS)[number]),
            )
            .map((name) => {
              const text =
                messages && typeof messages === "object"
                  ? (messages as Record<string, unknown>)[name]
                  : undefined;
              return {
                name,
                errors: [
                  typeof text === "string"
                    ? text
                    : t("admin.setup.companyErrors.VALIDATION_FAILED"),
                ],
              };
            }),
        );
      },
    },
  });

  if (company === null) {
    return (
      <div className="pf-panel-stack">
        <Alert type="info" showIcon message={t("admin.setup.companyUnknown")} />
        <Button loading={retrying} onClick={onRetry}>
          {t("admin.setup.companyRetry")}
        </Button>
      </div>
    );
  }
  if (!company.required) {
    return <p style={{ margin: 0 }}>{t("admin.setup.companyDone")}</p>;
  }
  if (!company.can_setup) {
    return <Alert type="warning" showIcon message={t("admin.setup.companyNoRights")} />;
  }

  return (
    <Form<Values>
      form={form}
      layout="vertical"
      requiredMark={false}
      onFinish={(values) => {
        const data: SetupCompanyIn = { name: values.name.trim() };
        if (values.inn?.trim()) data.inn = values.inn.trim();
        if (values.legal_address?.trim()) data.legal_address = values.legal_address.trim();
        if (values.phone?.trim()) data.phone = values.phone.trim();
        if (values.email?.trim()) data.email = values.email.trim();
        create.mutate({ data });
      }}
      className="pf-panel-stack"
      style={{ gap: 16 }}
    >
      <p style={{ margin: 0 }}>{t("admin.setup.companyRequired")}</p>
      <Form.Item
        name="name"
        label={t("admin.setup.companyName")}
        rules={[
          { required: true, whitespace: true, message: t("admin.setup.companyNameRequired") },
        ]}
        style={{ margin: 0 }}
      >
        <Input maxLength={255} autoComplete="organization" />
      </Form.Item>
      <Form.Item name="inn" label={t("admin.setup.companyInn")} style={{ margin: 0 }}>
        <Input maxLength={20} autoComplete="off" inputMode="numeric" />
      </Form.Item>
      <Form.Item name="legal_address" label={t("admin.setup.companyAddress")} style={{ margin: 0 }}>
        <Input autoComplete="street-address" />
      </Form.Item>
      <Form.Item name="phone" label={t("admin.setup.companyPhone")} style={{ margin: 0 }}>
        <Input maxLength={50} autoComplete="tel" inputMode="tel" />
      </Form.Item>
      <Form.Item
        name="email"
        label={t("admin.setup.companyEmail")}
        rules={[{ type: "email", message: t("admin.setup.companyEmailInvalid") }]}
        style={{ margin: 0 }}
      >
        <Input type="email" maxLength={254} autoComplete="off" inputMode="email" />
      </Form.Item>
      {create.isError &&
      !(create.error instanceof ApiError && create.error.code === "VALIDATION_FAILED") ? (
        <Alert type="error" showIcon role="alert" message={errorText(t, create.error)} />
      ) : null}
      <Consequence items={lines(t, "admin.setup.companyConsequence")} />
      <div>
        <Button type="primary" htmlType="submit" loading={create.isPending}>
          {t("admin.setup.companySubmit")}
        </Button>
      </div>
    </Form>
  );
}
