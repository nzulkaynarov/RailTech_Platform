import { useQueryClient } from "@tanstack/react-query";
import { App, Checkbox, Form, Input, Select } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import type { CompanyProfile } from "../../../../shared/api/generated/model";
import {
  getGetCompanyQueryKey,
  useDeleteCompanyLogo,
  useGetCompany,
  useListReferenceItems,
  useUpdateCompany,
  useUploadCompanyLogo,
} from "../../../../shared/api/generated/platform-bff";
import { StepSections } from "../../../../shared/ui/StepSections/StepSections";
import { ConfirmModal, LogoField, QueryGate, SaveBlock, TabHeader, ReadOnlyFence } from "../common";
import { localName } from "../../../eds/dictionaries";
import { changedFields, isEmptyObject } from "../diff";
import { errorFields } from "../errors";
import { BankAccounts } from "./BankAccounts";

interface Values {
  name: string;
  inn: string;
  legal_address: string;
  phone: string;
  contact_person: string;
  email: string;
  website: string;
  country: number | null;
  has_iso9001: boolean;
}

const toValues = (c: CompanyProfile): Values => ({
  name: c.name,
  inn: c.inn ?? "",
  legal_address: c.legal_address,
  phone: c.phone,
  contact_person: c.contact_person,
  email: c.email,
  website: c.website,
  country: c.country,
  has_iso9001: c.has_iso9001,
});

/** Поля секции «Контакты»: ошибка сохранения в них открывает эту секцию (platform-frontend.md §4.1a). */
const CONTACT_FIELDS: ReadonlySet<string> = new Set([
  "legal_address",
  "phone",
  "email",
  "contact_person",
  "website",
]);

type SectionKey = "company" | "contacts" | "bank";

/**
 * Реквизиты и логотип своей компании (ERP `accounts/companies/{id}`; BFF сам находит id по профилю сотрудника) — секциями
 * по шагам (§4.1a): «Компания», «Контакты», «Банковские счета». Настройки сохраняет бар внизу, секции «Проверка» нет.
 */
export function DetailsTab() {
  const { t } = useTranslation("company");
  const query = useGetCompany();
  // Открытая секция живёт выше формы: после сохранения форма пересоздаётся, а секция остаётся.
  // `?section=bank` — из мастера и уведомлений «нет реквизитов для счетов».
  const [params] = useSearchParams();
  const [active, setActive] = useState<SectionKey>(() =>
    params.get("section") === "bank" ? "bank" : "company",
  );
  return (
    <div className="pf-co-body">
      <TabHeader title={t("details.title")} hint={t("details.hint")} />
      <ReadOnlyFence>
        <QueryGate query={query}>
          {(company) => (
            <DetailsForm
              key={JSON.stringify({ ...company, logo_url: null })}
              company={company}
              active={active}
              setActive={setActive}
            />
          )}
        </QueryGate>
      </ReadOnlyFence>
    </div>
  );
}

function DetailsForm({
  company,
  active,
  setActive,
}: {
  company: CompanyProfile;
  active: SectionKey;
  setActive: (key: SectionKey) => void;
}) {
  const { t, i18n } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const initial = useMemo(() => toValues(company), [company]);
  const watched = Form.useWatch([], form);
  const changed = changedFields(initial, watched);
  const countries = useListReferenceItems("countries");
  const [removing, setRemoving] = useState(false);

  const sectionOf = (field: string): SectionKey =>
    CONTACT_FIELDS.has(field) ? "contacts" : "company";
  // до первой отрисовки полей useWatch отдаёт undefined — тогда итог секций из сохранённого
  const values: Partial<Values> = { ...initial, ...watched };
  const invalid = (key: SectionKey) =>
    form
      .getFieldsError()
      .some((entry) => entry.errors.length > 0 && sectionOf(String(entry.name[0])) === key);

  const keep = (next: CompanyProfile) => {
    queryClient.setQueryData(getGetCompanyQueryKey(), next);
  };
  const update = useUpdateCompany({
    mutation: {
      onSuccess: (next) => {
        keep(next);
        void message.success(t("saved"));
      },
    },
  });
  const upload = useUploadCompanyLogo({
    mutation: {
      onSuccess: (next) => {
        keep(next);
        void message.success(t("logo.uploaded"));
      },
    },
  });
  const remove = useDeleteCompanyLogo({
    mutation: {
      onSuccess: () => {
        keep({ ...company, logo_url: null });
        setRemoving(false);
        void message.success(t("logo.deleted"));
      },
    },
  });

  const submit = () => {
    update.mutate(
      { data: changed },
      {
        onError: (error) => {
          const fields = errorFields(error).filter((name) => name in initial);
          form.setFields(
            fields.map((name) => ({
              name: name as keyof Values,
              errors: [t("details.invalidField")],
            })),
          );
          if (fields[0]) setActive(sectionOf(fields[0]));
        },
      },
    );
  };

  return (
    <>
      <Form<Values>
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={submit}
        onFinishFailed={({ errorFields: failed }) => {
          const first = failed[0]?.name[0];
          if (first !== undefined) setActive(sectionOf(String(first)));
        }}
      >
        <StepSections
          headingLevel={3}
          active={active}
          onActiveChange={(key) => {
            setActive(key as SectionKey);
          }}
          sections={[
            {
              key: "company",
              title: t("details.sections.company"),
              summary: [values.name, values.inn].filter(Boolean).join(" · "),
              complete: Boolean(values.name?.trim()),
              invalid: invalid("company"),
              content: (
                <>
                  <LogoField
                    url={company.logo_url}
                    label={t("details.logo")}
                    uploading={upload.isPending}
                    deleting={remove.isPending}
                    error={upload.error ?? remove.error}
                    onUpload={(file) => {
                      upload.mutate({ data: { logo: file } });
                    }}
                    onDelete={() => {
                      remove.reset();
                      setRemoving(true);
                    }}
                  />
                  <ConfirmModal
                    open={removing}
                    title={t("logo.deleteTitle")}
                    okLabel={t("logo.delete")}
                    danger
                    loading={remove.isPending}
                    error={remove.error}
                    onOk={() => {
                      remove.mutate();
                    }}
                    onCancel={() => {
                      setRemoving(false);
                    }}
                  />
                  <div className="pf-co-grid">
                    <Form.Item
                      name="name"
                      label={t("details.name")}
                      rules={[
                        { required: true, whitespace: true, message: t("details.nameRequired") },
                      ]}
                      className="pf-co-wide"
                    >
                      <Input maxLength={255} autoComplete="organization" />
                    </Form.Item>
                    <Form.Item
                      name="inn"
                      label={t("details.inn")}
                      rules={[{ pattern: /^(\d{9})?$/, message: t("details.innInvalid") }]}
                      extra={t("details.innHint")}
                    >
                      <Input maxLength={9} inputMode="numeric" autoComplete="off" />
                    </Form.Item>
                    <Form.Item name="country" label={t("details.country")}>
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        loading={countries.isPending}
                        options={(countries.data?.items ?? []).map((c) => ({
                          value: Number(c.id),
                          label: c.names ? localName(c.names, i18n.language) : c.name,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item name="has_iso9001" valuePropName="checked" className="pf-co-wide">
                      <Checkbox>{t("details.iso")}</Checkbox>
                    </Form.Item>
                  </div>
                </>
              ),
            },
            {
              key: "contacts",
              title: t("details.sections.contacts"),
              summary: [values.phone, values.email].filter(Boolean).join(" · "),
              complete: Boolean(values.phone?.trim() || values.email?.trim()),
              invalid: invalid("contacts"),
              content: (
                <div className="pf-co-grid">
                  <Form.Item
                    name="legal_address"
                    label={t("details.legalAddress")}
                    className="pf-co-wide"
                  >
                    <Input.TextArea rows={2} autoComplete="street-address" />
                  </Form.Item>
                  <Form.Item name="phone" label={t("details.phone")}>
                    <Input maxLength={50} type="tel" autoComplete="tel" />
                  </Form.Item>
                  <Form.Item
                    name="email"
                    label={t("details.email")}
                    rules={[{ type: "email", message: t("details.emailInvalid") }]}
                  >
                    <Input maxLength={254} type="email" autoComplete="email" inputMode="email" />
                  </Form.Item>
                  <Form.Item name="contact_person" label={t("details.contactPerson")}>
                    <Input maxLength={255} autoComplete="name" />
                  </Form.Item>
                  <Form.Item name="website" label={t("details.website")}>
                    <Input maxLength={255} type="url" autoComplete="url" inputMode="url" />
                  </Form.Item>
                </div>
              ),
            },
            {
              key: "bank",
              title: t("bank.title"),
              content: <BankAccounts />,
            },
          ]}
        />
        <SaveBlock
          label={t("details.save")}
          loading={update.isPending}
          disabled={isEmptyObject(changed)}
          error={update.error}
          onDiscard={() => {
            form.resetFields();
            update.reset();
          }}
        />
      </Form>
    </>
  );
}
