import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, AutoComplete, Button, Checkbox, Form, Input, Radio, Select } from "antd";
import { RowActions, ROW_ACTIONS_WIDTH } from "../../../../shared/ui/RowActions";
import type { FormInstance, SelectProps } from "antd";
import { useEffect, useId, useState } from "react";
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
  useListDictionaryItems,
  useListReferenceItems,
  useUpdateCompanyBankAccount,
  getGetSetupChecklistQueryKey,
} from "../../../../shared/api/generated/platform-bff";
import {
  accountProblem,
  compact,
  countryOf,
  grouped,
  latinProblem,
  mfoProblem,
  placeOf,
  swiftProblem,
  type BankPlace,
} from "../../../../shared/lib/bankAccount";
import { HOME_CURRENCY } from "../../../../shared/lib/money";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { useSheetPanel } from "../../../../shared/ui/useSheetPanel";
import { ConfirmModal, FormSheet, ListTable, QueryGate } from "../common";
import { changedFields, codeLabel } from "../diff";
import { errorFields, fieldReasons } from "../errors";

interface Values {
  place: BankPlace;
  account: string;
  currency: string;
  holder_name_latin: string;
  bank_name: string;
  bank_address: string;
  mfo: string;
  swift: string;
  intermediary_swift: string;
  intermediary_account: string;
  is_default: boolean;
  is_active: boolean;
}

const EMPTY: Values = {
  place: "uz",
  account: "",
  currency: HOME_CURRENCY,
  holder_name_latin: "",
  bank_name: "",
  bank_address: "",
  mfo: "",
  swift: "",
  intermediary_swift: "",
  intermediary_account: "",
  is_default: false,
  is_active: true,
};

const valuesOf = (row: CompanyBankAccount): Values => ({
  place: placeOf(row.bank_country),
  account: row.account,
  currency: row.currency,
  holder_name_latin: row.holder_name_latin,
  bank_name: row.bank_name,
  bank_address: row.bank_address,
  mfo: row.mfo,
  swift: row.swift,
  intermediary_swift: row.intermediary_swift,
  intermediary_account: row.intermediary_account,
  is_default: row.is_default,
  is_active: row.is_active,
});

const CODES = ["account", "mfo", "swift", "intermediary_swift", "intermediary_account"] as const;

/** Значения формы — тело запроса: коды без пробелов, страна банка — UZ или из SWIFT (ADR-0029). */
function payloadOf(values: Values) {
  const { place, ...rest } = values;
  const body = { ...rest, bank_country: countryOf(place, values.swift) };
  for (const key of CODES) body[key] = compact(body[key]);
  if (place === "uz") {
    body.holder_name_latin = "";
    body.bank_address = "";
    body.intermediary_swift = "";
    body.intermediary_account = "";
  }
  return body;
}

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
    Promise.all([
      queryClient.invalidateQueries({ queryKey: getListCompanyBankAccountsQueryKey() }),
      // Баннер и мастер «Нет банковских реквизитов» видят счёт сразу (СЦ-3), а не через полминуты.
      queryClient.invalidateQueries({ queryKey: getGetSetupChecklistQueryKey() }),
    ]);
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
                    width: 280,
                    cell: (row) => (
                      <span className="pf-num">
                        {grouped(row.account)}
                        {row.bank_country && row.bank_country !== "UZ"
                          ? ` · ${row.bank_country}`
                          : ""}
                      </span>
                    ),
                  },
                  {
                    id: "currency",
                    header: t("bank.currency"),
                    width: 90,
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
                    headerHidden: true,
                    width: ROW_ACTIONS_WIDTH,
                    cell: (row) => (
                      <RowActions
                        name={row.account}
                        items={[
                          {
                            key: "edit",
                            label: t("edit"),
                            onClick: () => {
                              setEditing(row);
                            },
                          },
                          {
                            key: "delete",
                            label: t("delete"),
                            danger: true,
                            onClick: () => {
                              remove.reset();
                              setRemoving(row);
                            },
                          },
                        ]}
                      />
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

/**
 * Выбор с поиском в обязательном поле формы: Form.Item ставит `aria-required` на корень antd Select (`div` без роли —
 * axe aria-allowed-attr); обязательность и так видна в метке и проверяется правилом формы.
 */
function SearchSelect(props: SelectProps & { "aria-required"?: unknown }) {
  const rest: SelectProps & { "aria-required"?: unknown } = { ...props };
  delete rest["aria-required"];
  return <Select {...rest} />;
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
  // Банки из справочника ЦБ: МФО из справочника задаёт название банка без вариантов; МФО, которого там нет
  // (новый филиал, справочник старый), не тупик — банк вписывают руками, форма предупреждает
  const { i18n } = useTranslation();
  const banks = useListDictionaryItems("banks", undefined, { query: { staleTime: 5 * 60_000 } });
  const lang = (["ru", "uz", "en"] as const).find((l) => i18n.language.startsWith(l)) ?? "ru";
  const bankOptions = (banks.data?.items ?? []).map((bank) => {
    const name = bank.name[lang] || bank.name.ru;
    return {
      value: bank.code,
      label: `${bank.code} · ${name}`,
      name,
      swift: String(bank.attrs["swift"] ?? ""),
    };
  });
  const bankByCode = new Map(bankOptions.map((option) => [option.value, option]));
  // СЦ-3: пустой справочник банков — не повод запирать поле: МФО не найден, название банка вписывается вручную.
  const directoryReady = !banks.isPending;
  const onMfoChange = (value: string) => {
    const known = bankByCode.get(compact(value));
    const previous = bankOptions.find((option) => option.name === form.getFieldValue("bank_name"));
    if (known) {
      const swift = String(form.getFieldValue("swift") ?? "");
      form.setFieldsValue({
        bank_name: known.name,
        ...(known.swift && (!swift || swift === previous?.swift) ? { swift: known.swift } : {}),
      });
    } else if (previous) {
      // Банк прежнего МФО из справочника к новому не подходит — вместе с его SWIFT
      form.setFieldsValue({
        bank_name: "",
        ...(previous.swift && form.getFieldValue("swift") === previous.swift ? { swift: "" } : {}),
      });
    }
  };
  const create = useCreateCompanyBankAccount({ mutation: { onSuccess: onSaved } });
  const update = useUpdateCompanyBankAccount({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;
  // До первого рендера формы useWatch отдаёт undefined, хотя тип его не допускает.
  const placeOr = (value: BankPlace | undefined): BankPlace => value ?? initial.place;
  const place = placeOr(Form.useWatch("place", form));
  const abroad = place === "abroad";
  const mfo = compact(Form.useWatch("mfo", form));
  const knownBank = abroad ? undefined : bankByCode.get(mfo);
  const unknownMfo = !abroad && directoryReady && !knownBank && mfoProblem("uz", mfo) === null;
  // МФО ввели раньше, чем пришёл справочник, или открыли счёт с устаревшим названием — банк всё равно из справочника
  const knownName = knownBank?.name;
  useEffect(() => {
    if (knownName !== undefined && form.getFieldValue("bank_name") !== knownName) {
      form.setFieldsValue({ bank_name: knownName });
    }
  }, [form, knownName]);
  const reasonText = (reason: string) =>
    t(`bank.errors.${reason}`, { defaultValue: t("bank.invalidField") });
  const check =
    (problem: (value: string) => string | null) => (_rule: unknown, value: string | undefined) => {
      const reason = problem(value ?? "");
      return reason ? Promise.reject(new Error(reasonText(reason))) : Promise.resolve();
    };

  const submit = (values: Values) => {
    const onError = (error: unknown) => {
      const reasons = fieldReasons(error);
      form.setFields(
        errorFields(error)
          .filter((name) => name in EMPTY)
          .map((name) => ({
            name: name as keyof Values,
            errors: [reasons[name] ? reasonText(reasons[name]) : t("bank.invalidField")],
          })),
      );
    };
    const body = payloadOf(values);
    if (row) {
      update.mutate({ id: row.id, data: changedFields(payloadOf(initial), body) }, { onError });
    } else {
      create.mutate({ data: body satisfies CompanyBankAccountIn }, { onError });
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
        <Form.Item name="place" label={t("bank.place")}>
          <Radio.Group
            optionType="button"
            options={[
              { value: "uz", label: t("bank.places.uz") },
              { value: "abroad", label: t("bank.places.abroad") },
            ]}
          />
        </Form.Item>
        <div className="pf-co-grid">
          <Form.Item
            name="currency"
            label={t("bank.currency")}
            rules={[{ required: true, message: t("required") }]}
          >
            <SearchSelect
              showSearch
              optionFilterProp="label"
              loading={currencies.isPending}
              options={(currencies.data?.items ?? []).map((c) => ({
                value: c.code,
                label: codeLabel(c.code, c.name),
              }))}
            />
          </Form.Item>
          {abroad ? (
            <Form.Item
              name="swift"
              label={t("bank.swift")}
              extra={t("bank.swiftHint")}
              rules={[{ validator: check((v) => swiftProblem(v, true)) }]}
            >
              <Input maxLength={11} autoComplete="off" className="pf-num" />
            </Form.Item>
          ) : (
            <Form.Item
              name="mfo"
              label={t("bank.mfo")}
              validateTrigger="onBlur"
              rules={[{ validator: check((v) => mfoProblem("uz", v)) }]}
              {...(unknownMfo
                ? { validateStatus: "warning" as const, help: t("bank.mfoNotInDirectory") }
                : {})}
            >
              <AutoComplete
                options={bankOptions}
                onChange={onMfoChange}
                filterOption={(input, option) =>
                  (option?.label ?? "").toLowerCase().includes(input.trim().toLowerCase())
                }
                popupMatchSelectWidth={320}
              >
                <Input autoComplete="off" className="pf-num" />
              </AutoComplete>
            </Form.Item>
          )}
        </div>
        {abroad ? (
          <Form.Item
            name="holder_name_latin"
            label={t("bank.holderLatin")}
            extra={t("bank.holderLatinHint")}
            rules={[{ validator: check(latinProblem) }]}
          >
            <Input maxLength={140} autoComplete="off" />
          </Form.Item>
        ) : null}
        <Form.Item
          name="account"
          label={abroad ? t("bank.iban") : t("bank.account")}
          extra={abroad ? t("bank.ibanHint") : t("bank.accountHint")}
          dependencies={["currency", "place"]}
          rules={[
            {
              validator: check((v) =>
                accountProblem(place, v, String(form.getFieldValue("currency") ?? "")),
              ),
            },
          ]}
        >
          <Input
            maxLength={42}
            autoComplete="off"
            inputMode={abroad ? "text" : "numeric"}
            className="pf-num"
          />
        </Form.Item>
        <div className="pf-co-grid">
          <Form.Item
            name="bank_name"
            label={t("bank.bankName")}
            extra={
              abroad
                ? t("bank.autoHint")
                : knownBank
                  ? t("bank.fromDirectory")
                  : unknownMfo
                    ? undefined
                    : t("bank.mfoFirst")
            }
            rules={unknownMfo ? [{ required: true, whitespace: true, message: t("required") }] : []}
          >
            <Input
              maxLength={255}
              autoComplete="off"
              readOnly={!abroad && !unknownMfo}
              variant={!abroad && !unknownMfo ? "filled" : "outlined"}
            />
          </Form.Item>
          {abroad ? (
            <Form.Item name="bank_address" label={t("bank.bankAddress")}>
              <Input maxLength={255} autoComplete="off" />
            </Form.Item>
          ) : (
            <Form.Item
              name="swift"
              label={t("bank.swiftOptional")}
              rules={[{ validator: check((v) => swiftProblem(v, false)) }]}
            >
              <Input maxLength={11} autoComplete="off" className="pf-num" />
            </Form.Item>
          )}
        </div>
        {abroad ? (
          <div className="pf-co-grid">
            <Form.Item
              name="intermediary_swift"
              label={t("bank.intermediarySwift")}
              dependencies={["intermediary_account"]}
              rules={[
                {
                  validator: check((v) =>
                    swiftProblem(
                      v,
                      Boolean(compact(String(form.getFieldValue("intermediary_account") ?? ""))),
                    ),
                  ),
                },
              ]}
            >
              <Input maxLength={11} autoComplete="off" className="pf-num" />
            </Form.Item>
            <Form.Item name="intermediary_account" label={t("bank.intermediaryAccount")}>
              <Input maxLength={50} autoComplete="off" className="pf-num" />
            </Form.Item>
          </div>
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
