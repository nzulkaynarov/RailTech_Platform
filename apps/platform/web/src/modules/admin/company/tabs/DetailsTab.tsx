import { useQueryClient } from "@tanstack/react-query";
import { App, Checkbox, Form, Input, Select } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CompanyProfile } from "../../../../shared/api/generated/model";
import {
  getGetCompanyQueryKey,
  useDeleteCompanyLogo,
  useGetCompany,
  useListReferenceItems,
  useUpdateCompany,
  useUploadCompanyLogo,
} from "../../../../shared/api/generated/platform-bff";
import { ConfirmModal, LogoField, QueryGate, SaveBlock, TabHeader, ReadOnlyFence } from "../common";
import { changedFields, isEmptyObject } from "../diff";
import { errorFields } from "../errors";

interface Values {
  name: string;
  inn: string;
  legal_address: string;
  bank_account: string;
  mfo: string;
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
  bank_account: c.bank_account,
  mfo: c.mfo,
  phone: c.phone,
  contact_person: c.contact_person,
  email: c.email,
  website: c.website,
  country: c.country,
  has_iso9001: c.has_iso9001,
});

/** Реквизиты и логотип своей компании (ERP `accounts/companies/{id}`; BFF сам находит id по профилю сотрудника). */
export function DetailsTab() {
  const { t } = useTranslation("company");
  const query = useGetCompany();
  return (
    <div className="pf-co-body">
      <TabHeader title={t("details.title")} hint={t("details.hint")} />
      <ReadOnlyFence>
        <QueryGate query={query}>
          {(company) => (
            <DetailsForm key={JSON.stringify({ ...company, logo_url: null })} company={company} />
          )}
        </QueryGate>
      </ReadOnlyFence>
    </div>
  );
}

function DetailsForm({ company }: { company: CompanyProfile }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const initial = useMemo(() => toValues(company), [company]);
  const watched = Form.useWatch([], form);
  const changed = changedFields(initial, watched);
  const countries = useListReferenceItems("countries");
  const [removing, setRemoving] = useState(false);

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
          form.setFields(
            errorFields(error)
              .filter((name) => name in initial)
              .map((name) => ({ name: name as keyof Values, errors: [t("details.invalidField")] })),
          );
        },
      },
    );
  };

  return (
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
        items={[t("logo.consequence.card"), t("logo.consequence.file")]}
        onOk={() => {
          remove.mutate();
        }}
        onCancel={() => {
          setRemoving(false);
        }}
      />
      <Form<Values> form={form} layout="vertical" initialValues={initial} onFinish={submit}>
        <div className="pf-co-grid">
          <Form.Item
            name="name"
            label={t("details.name")}
            rules={[{ required: true, whitespace: true, message: t("details.nameRequired") }]}
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
                label: c.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="legal_address" label={t("details.legalAddress")} className="pf-co-wide">
            <Input.TextArea rows={2} autoComplete="street-address" />
          </Form.Item>
          <Form.Item name="bank_account" label={t("details.bankAccount")}>
            <Input maxLength={50} autoComplete="off" inputMode="numeric" />
          </Form.Item>
          <Form.Item name="mfo" label={t("details.mfo")}>
            <Input maxLength={10} autoComplete="off" inputMode="numeric" />
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
          <Form.Item name="has_iso9001" valuePropName="checked" className="pf-co-wide">
            <Checkbox>{t("details.iso")}</Checkbox>
          </Form.Item>
        </div>
        <SaveBlock
          label={t("details.save")}
          loading={update.isPending}
          disabled={isEmptyObject(changed)}
          error={update.error}
          consequence={[t("details.consequence.erp"), t("details.consequence.brand")]}
        />
      </Form>
    </>
  );
}
