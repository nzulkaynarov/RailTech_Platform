import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Form, Input, Select } from "antd";
import type { FormInstance } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CompanyBankAccount,
  CompanyBankAccountIn,
} from "../../../../shared/api/generated/model";
import {
  getListCompanyBankAccountsQueryKey,
  useCreateCompanyBankAccount,
  useDeleteCompanyBankAccount,
  useListCompanyBankAccounts,
  useListReferenceItems,
  useUpdateCompanyBankAccount,
} from "../../../../shared/api/generated/platform-bff";
import { HOME_CURRENCY } from "../../../../shared/lib/money";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { useSheetPanel } from "../../../../shared/ui/useSheetPanel";
import { ConfirmModal, FormSheet, ListTable, QueryGate } from "../common";
import { changedFields, codeLabel } from "../diff";
import { errorFields } from "../errors";

interface Values {
  account: string;
  currency: string;
  bank_name: string;
  mfo: string;
  swift: string;
  correspondent_bank: string;
  is_default: boolean;
  is_active: boolean;
}

const EMPTY: Values = {
  account: "",
  currency: HOME_CURRENCY,
  bank_name: "",
  mfo: "",
  swift: "",
  correspondent_bank: "",
  is_default: false,
  is_active: true,
};

const valuesOf = (row: CompanyBankAccount): Values => ({
  account: row.account,
  currency: row.currency,
  bank_name: row.bank_name,
  mfo: row.mfo,
  swift: row.swift,
  correspondent_bank: row.correspondent_bank,
  is_default: row.is_default,
  is_active: row.is_active,
});

/**
 * Банковские счета своей компании (решение владельца 2026-11-11): основной, дополнительные, валютные; один основной на
 * валюту. Документы печатают основной счёт своей валюты, без него — основной в сумах; без него счёт клиенту не выставить.
 */
export function BankAccounts() {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useListCompanyBankAccounts();
  const [editing, setEditingState] = useState<CompanyBankAccount | "new" | null>(null);
  // Счёт — короткая форма о выбранной строке: в боковом окне (§4.1a). Экземпляр формы — здесь: при смене ширины окно и
  // лист на весь экран пересоздают форму, а набранное остаётся.
  const panel = useSheetPanel();
  const [accountForm] = Form.useForm<Values>();
  const setEditing = (next: CompanyBankAccount | "new") => {
    accountForm.resetFields();
    setEditingState(next);
    panel.open();
  };
  const closeEditing = () => {
    setEditingState(null);
    panel.close();
  };
  const [removing, setRemoving] = useState<CompanyBankAccount | null>(null);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getListCompanyBankAccountsQueryKey() });
  const remove = useDeleteCompanyBankAccount({
    mutation: {
      onSuccess: () => {
        void refresh();
        setRemoving(null);
        void message.success(t("bank.deleted"));
      },
    },
  });
  const add = (
    <Button
      onClick={() => {
        setEditing("new");
      }}
    >
      {t("bank.add")}
    </Button>
  );
  return (
    // Заголовок — у секции «Банковские счета» реквизитов (StepSections)
    <div className="pf-co-section">
      <QueryGate query={query}>
        {({ items }) => {
          const ready = items.some(
            (r) => r.is_active && r.is_default && r.currency === HOME_CURRENCY,
          );
          return (
            <>
              <Alert
                type={ready ? "success" : "warning"}
                showIcon
                role="status"
                message={t(ready ? "details.bankReady" : "details.bankMissing")}
              />
              {items.length > 0 ? <div>{add}</div> : null}
              <ListTable<CompanyBankAccount>
                tableId="admin.company.bankAccounts"
                label={t("bank.title")}
                data={items}
                rowKey={(row) => row.id}
                empty={{ title: t("bank.empty.title"), text: t("bank.empty.text"), action: add }}
                columns={[
                  {
                    id: "account",
                    header: t("bank.account"),
                    width: null,
                    cell: (row) => <span className="pf-num">{row.account}</span>,
                  },
                  {
                    id: "currency",
                    header: t("bank.currency"),
                    width: null,
                    cell: (row) => row.currency,
                  },
                  {
                    id: "bank_name",
                    header: t("bank.bankName"),
                    width: null,
                    cell: (row) => row.bank_name,
                  },
                  {
                    id: "is_default",
                    header: t("bank.isDefault"),
                    width: null,
                    cell: (row) => (row.is_default ? t("yes") : t("no")),
                  },
                  {
                    id: "is_active",
                    header: t("status"),
                    width: null,
                    cell: (row) => (
                      <StatusTag kind="activity" status={row.is_active ? "active" : "inactive"}>
                        {row.is_active ? t("active") : t("inactive")}
                      </StatusTag>
                    ),
                  },
                  {
                    id: "actions",
                    header: t("actions"),
                    width: 160,
                    cell: (row) => (
                      <span className="pf-co-actions">
                        <Button
                          type="link"
                          size="small"
                          aria-label={t("editNamed", { name: row.account })}
                          onClick={() => {
                            setEditing(row);
                          }}
                        >
                          {t("edit")}
                        </Button>
                        <Button
                          type="link"
                          size="small"
                          danger
                          aria-label={t("deleteNamed", { name: row.account })}
                          onClick={() => {
                            remove.reset();
                            setRemoving(row);
                          }}
                        >
                          {t("delete")}
                        </Button>
                      </span>
                    ),
                  },
                ]}
              />
            </>
          );
        }}
      </QueryGate>
      {editing !== null ? (
        <BankAccountForm
          key={editing === "new" ? "new" : editing.id}
          form={accountForm}
          row={editing === "new" ? null : editing}
          onClose={closeEditing}
          onSaved={() => {
            void refresh();
            closeEditing();
            void message.success(t("saved"));
          }}
        />
      ) : null}
      <ConfirmModal
        open={removing !== null}
        title={t("bank.deleteTitle", { name: removing?.account ?? "" })}
        okLabel={t("delete")}
        danger
        loading={remove.isPending}
        error={remove.error}
        onOk={() => {
          if (removing) remove.mutate({ id: removing.id });
        }}
        onCancel={() => {
          setRemoving(null);
        }}
      />
    </div>
  );
}

function BankAccountForm({
  form,
  row,
  onClose,
  onSaved,
}: {
  form: FormInstance<Values>;
  row: CompanyBankAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const initial = row ? valuesOf(row) : EMPTY;
  const currencies = useListReferenceItems("currencies");
  const create = useCreateCompanyBankAccount({ mutation: { onSuccess: onSaved } });
  const update = useUpdateCompanyBankAccount({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;
  const foreign = Form.useWatch("currency", form) !== HOME_CURRENCY;

  const submit = (values: Values) => {
    const onError = (error: unknown) => {
      form.setFields(
        errorFields(error)
          .filter((name) => name in EMPTY)
          .map((name) => ({ name: name as keyof Values, errors: [t("bank.invalidField")] })),
      );
    };
    if (row) {
      update.mutate({ id: row.id, data: changedFields(initial, values) }, { onError });
    } else {
      create.mutate({ data: values satisfies CompanyBankAccountIn }, { onError });
    }
  };

  return (
    <FormSheet
      title={row ? t("bank.editTitle") : t("bank.addTitle")}
      formId={formId}
      submitLabel={t("save")}
      saving={mutation.isPending}
      error={
        mutation.error && errorFields(mutation.error).length === 0 ? mutation.error : undefined
      }
      onCancel={onClose}
    >
      <Form<Values>
        id={formId}
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={submit}
      >
        <Form.Item
          name="currency"
          label={t("bank.currency")}
          rules={[{ required: true, message: t("required") }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={currencies.isPending}
            options={(currencies.data?.items ?? []).map((c) => ({
              value: c.code,
              label: codeLabel(c.code, c.name),
            }))}
          />
        </Form.Item>
        <Form.Item
          name="account"
          label={t("bank.account")}
          rules={[{ required: true, message: t("required") }]}
        >
          <Input maxLength={50} autoComplete="off" inputMode="numeric" />
        </Form.Item>
        <div className="pf-co-grid">
          <Form.Item name="bank_name" label={t("bank.bankName")}>
            <Input maxLength={255} autoComplete="off" />
          </Form.Item>
          <Form.Item name="mfo" label={t("bank.mfo")}>
            <Input maxLength={10} autoComplete="off" inputMode="numeric" />
          </Form.Item>
        </div>
        {foreign ? (
          <>
            <Form.Item name="swift" label={t("bank.swift")}>
              <Input maxLength={11} autoComplete="off" />
            </Form.Item>
            <Form.Item name="correspondent_bank" label={t("bank.correspondent")}>
              <Input.TextArea rows={2} maxLength={2000} />
            </Form.Item>
          </>
        ) : null}
        <Form.Item name="is_default" valuePropName="checked" style={{ marginBottom: 4 }}>
          <Checkbox>{t("bank.isDefaultLabel")}</Checkbox>
        </Form.Item>
        <Form.Item name="is_active" valuePropName="checked" style={{ marginBottom: 0 }}>
          <Checkbox>{t("bank.activeLabel")}</Checkbox>
        </Form.Item>
      </Form>
    </FormSheet>
  );
}
