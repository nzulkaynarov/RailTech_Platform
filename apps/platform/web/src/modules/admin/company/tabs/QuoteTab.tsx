import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, InputNumber, Select, Switch } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { QuoteDefaults } from "../../../../shared/api/generated/model";
import {
  getGetQuoteDefaultsQueryKey,
  useGetQuoteDefaults,
  useListContractTemplates,
  useListReferenceItems,
  useUpdateQuoteDefaults,
} from "../../../../shared/api/generated/platform-bff";
import { QueryGate, SaveBlock, TabHeader, ReadOnlyFence } from "../common";
import { changedFields, codeLabel, isEmptyObject } from "../diff";
import { errorFields } from "../errors";
import { UnitLabel } from "../../../../shared/ui/UnitLabel";
import { unitOf } from "../../../../shared/lib/unit";
import { decimalInputProps } from "../../../../shared/lib/numberInput";

type Values = Partial<QuoteDefaults>;

/**
 * РАСЧ-3: цену клиенту ставит одна цифра — целевая маржа; шаг округления рядом. Поле «Маржа по умолчанию»
 * (`default_margin_percent`) с экрана убрано: колонка остаётся до чистки, значение не переносится.
 */
const MARGINS = ["min_margin_percent", "target_margin_percent", "price_rounding_step"] as const;

/**
 * Условия нового КП разнесены по страницам своих дел (ДОК-13, решение владельца 2026-11-20): «Продажи» — срок, оплата,
 * гарантия, маржа, базис; «Каталог» — цена и порог карточки; «Налоги и валюты» — валюта, НДС и возраст курса;
 * «Уведомления» — напоминания о счетах и актах; «Свежесть цен поставщиков» — отдельная карточка рядом с каталогом. Одна и та же запись настроек компании ERP, у каждой страницы свои поля.
 */
export type QuoteGroup =
  "sales" | "requests" | "contracts" | "catalog" | "supplier" | "taxes" | "reminders";

const GROUPS: Record<QuoteGroup, readonly (keyof QuoteDefaults)[]> = {
  sales: [
    "default_delivery_basis",
    ...MARGINS,
    "default_offer_validity_days",
    "payment_terms_days",
    "default_warranty_months",
    "default_payment_terms",
  ],
  // РЕЗ-1: что происходит с заявкой до расчёта — настройка, не зашитый шаг
  requests: ["request_resolution"],
  // ДОК-10: правила договора по утверждённому шаблону — данные компании, не код
  contracts: [
    "contract_auto_send",
    "contract_sign_before_send",
    "contract_deviations_allowed",
    "contract_four_eyes",
    "default_client_contract_template",
    "default_partner_contract_template",
    "partner_base_roles",
    // ДС-1: срок договора — правило, продление, напоминания и что делать после окончания
    "contract_term_rule",
    "contract_auto_renew",
    "contract_notice_days",
    "contract_next_year_from_day",
    "contract_remind_first_days",
    "contract_remind_last_days",
    "contract_foreign_remind_days",
    "contract_expired_action",
    "contract_foreign_by_agreement",
    "contract_gating_kinds",
  ],
  catalog: [
    "catalog_price_visibility",
    "catalog_publish_threshold",
    "catalog_require_mxik",
    "catalog_require_hs_imported",
  ],
  // Свежесть цен поставщиков — закупка, а не условия КП (ЕВ-2а, отчёт §8.2 п. 13): своя карточка рядом с каталогом
  supplier: ["offer_confirm_days", "offer_expiring_days"],
  taxes: ["default_cost_currency", "default_vat_rate", "fx_rate_max_age_days"],
  reminders: ["remind_overdue_invoices", "act_reminder_hours"],
};

/** Настройки договоров, спрятанные под «Дополнительно»: срок, продление и шаблоны остаются на виду. */
const CONTRACT_EXTRA: readonly (keyof QuoteDefaults)[] = [
  "contract_auto_send",
  "contract_sign_before_send",
  "contract_deviations_allowed",
  "contract_four_eyes",
  "contract_next_year_from_day",
  "contract_remind_first_days",
  "contract_remind_last_days",
  "contract_foreign_remind_days",
  "contract_expired_action",
  "contract_foreign_by_agreement",
  "contract_gating_kinds",
];

const pick = (defaults: QuoteDefaults, group: QuoteGroup): Values =>
  Object.fromEntries(
    GROUPS[group].filter((key) => key in defaults).map((key) => [key, defaults[key]]),
  );

/** Часть условий КП (ERP `companies/{id}/settings`) на своей странице Настроек. */
export function QuoteSettings({ group }: { group: QuoteGroup }) {
  const { t } = useTranslation("company");
  const query = useGetQuoteDefaults();
  return (
    <div className="pf-co-body">
      <TabHeader title={t(`quote.groups.${group}.title`)} hint={t(`quote.groups.${group}.hint`)} />
      <ReadOnlyFence>
        <QueryGate query={query}>
          {(defaults) => (
            <QuoteForm
              key={JSON.stringify(pick(defaults, group))}
              defaults={defaults}
              group={group}
            />
          )}
        </QueryGate>
      </ReadOnlyFence>
    </div>
  );
}

const NUMBER = { style: { width: "100%" } } as const;

function QuoteForm({ defaults, group }: { defaults: QuoteDefaults; group: QuoteGroup }) {
  const { t, i18n } = useTranslation("company");
  const decimal = decimalInputProps(i18n.language);
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const initial = useMemo<Values>(() => pick(defaults, group), [defaults, group]);
  const [more, setMore] = useState(false);
  const shows = (name: keyof QuoteDefaults) =>
    GROUPS[group].includes(name) &&
    (group !== "contracts" || more || !CONTRACT_EXTRA.includes(name));
  const watched = Form.useWatch([], form);
  const changed = changedFields(initial, watched);
  const currencies = useListReferenceItems("currencies");
  const bases = useListReferenceItems("delivery-basis");
  const contractTemplates = useListContractTemplates({ query: { enabled: group === "contracts" } });
  /** Шаблонами по умолчанию могут быть только утверждённые действующие шаблоны вида контрагента. */
  const templateOptions = (counterparty: "client" | "partner") =>
    (contractTemplates.data?.items ?? [])
      .filter(
        (row) => row.status === "approved" && row.is_active && row.counterparty === counterparty,
      )
      .map((row) => ({
        value: Number(row.id),
        label: `${row.name} · ${t("quote.edition", { n: row.edition })}`,
      }));
  // Без права на группу `cost_margin` BFF не присылает поля маржи совсем.
  const marginsVisible = defaults.target_margin_percent !== undefined;

  const update = useUpdateQuoteDefaults({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetQuoteDefaultsQueryKey(), next);
        void message.success(t("saved"));
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
              .map((name) => ({ name: name as keyof Values, errors: [t("quote.invalidField")] })),
          );
        },
      },
    );
  };

  const active = (items: { code: string; name: string; is_active: boolean }[] | undefined) =>
    (items ?? [])
      .filter((i) => i.is_active)
      .map((i) => ({ value: i.code, label: codeLabel(i.code, i.name) }));

  return (
    <Form<Values> form={form} layout="vertical" initialValues={initial} onFinish={submit}>
      {group === "sales" && !marginsVisible ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t("quote.marginHidden")}
        />
      ) : null}
      <div className="pf-co-grid">
        {shows("default_cost_currency") ? (
          <Form.Item
            name="default_cost_currency"
            label={t("quote.currency")}
            extra={t("quote.currencyHint")}
          >
            <Select
              allowClear
              loading={currencies.isPending}
              options={active(currencies.data?.items)}
            />
          </Form.Item>
        ) : null}
        {shows("default_delivery_basis") ? (
          <Form.Item
            name="default_delivery_basis"
            label={t("quote.basis")}
            extra={t("quote.basisHint")}
          >
            <Select allowClear loading={bases.isPending} options={active(bases.data?.items)} />
          </Form.Item>
        ) : null}
        {shows("default_vat_rate") ? (
          <Form.Item name="default_vat_rate" label={<UnitLabel label={t("quote.vat")} />}>
            <InputNumber
              suffix={unitOf(t("quote.vat"))}
              stringMode
              min="0"
              max="100"
              step="0.5"
              {...decimal}
              {...NUMBER}
            />
          </Form.Item>
        ) : null}
        {group === "sales" && marginsVisible
          ? MARGINS.map((name) => {
              const step = name === "price_rounding_step";
              return (
                <Form.Item
                  key={name}
                  name={name}
                  label={<UnitLabel label={t(`quote.${name}`)} />}
                  extra={name === "min_margin_percent" ? undefined : t(`quote.${name}Hint`)}
                >
                  <InputNumber
                    suffix={unitOf(t(`quote.${name}`))}
                    stringMode
                    min="0"
                    max={step ? "1000000000" : "100"}
                    step={step ? "100" : "0.5"}
                    {...decimal}
                    {...NUMBER}
                  />
                </Form.Item>
              );
            })
          : null}
        {shows("default_offer_validity_days") ? (
          <Form.Item
            name="default_offer_validity_days"
            label={<UnitLabel label={t("quote.validity")} />}
          >
            <InputNumber suffix={unitOf(t("quote.validity"))} min={0} precision={0} {...NUMBER} />
          </Form.Item>
        ) : null}
        {shows("payment_terms_days") ? (
          <Form.Item name="payment_terms_days" label={<UnitLabel label={t("quote.paymentDays")} />}>
            <InputNumber
              suffix={unitOf(t("quote.paymentDays"))}
              min={0}
              precision={0}
              {...NUMBER}
            />
          </Form.Item>
        ) : null}
        {shows("remind_overdue_invoices") ? (
          <Form.Item
            name="remind_overdue_invoices"
            label={t("quote.remindOverdue")}
            extra={t("quote.remindOverdueHint")}
            valuePropName="checked"
            className="pf-co-wide"
          >
            <Switch />
          </Form.Item>
        ) : null}
        {(
          [
            "contract_auto_send",
            "contract_sign_before_send",
            "contract_deviations_allowed",
            "contract_four_eyes",
          ] as const
        ).map((name) =>
          shows(name) ? (
            <Form.Item
              key={name}
              name={name}
              label={t(`quote.${name}`)}
              extra={t(`quote.${name}Hint`)}
              valuePropName="checked"
              className="pf-co-wide"
            >
              <Switch />
            </Form.Item>
          ) : null,
        )}
        {shows("default_client_contract_template") ? (
          <Form.Item
            name="default_client_contract_template"
            label={t("quote.defaultClientTemplate")}
          >
            <Select
              allowClear
              loading={contractTemplates.isPending}
              options={templateOptions("client")}
            />
          </Form.Item>
        ) : null}
        {shows("default_partner_contract_template") ? (
          <Form.Item
            name="default_partner_contract_template"
            label={t("quote.defaultPartnerTemplate")}
          >
            <Select
              allowClear
              loading={contractTemplates.isPending}
              options={templateOptions("partner")}
            />
          </Form.Item>
        ) : null}
        {shows("partner_base_roles") ? (
          <Form.Item
            name="partner_base_roles"
            label={t("quote.partner_base_roles")}
            extra={t("quote.partner_base_rolesHint")}
            className="pf-co-wide"
          >
            <Select
              mode="multiple"
              options={(["partnership", "nda", "offer"] as const).map((value) => ({
                value,
                label: t(`contractTemplates.baseRole.${value}`),
              }))}
            />
          </Form.Item>
        ) : null}
        {shows("contract_term_rule") ? (
          <Form.Item name="contract_term_rule" label={t("quote.contract_term_rule")}>
            <Select
              options={(["calendar_year", "twelve_months", "open"] as const).map((value) => ({
                value,
                label: t(`quote.termRule.${value}`),
              }))}
            />
          </Form.Item>
        ) : null}
        {shows("contract_auto_renew") ? (
          <Form.Item
            name="contract_auto_renew"
            label={t("quote.contract_auto_renew")}
            extra={t("quote.contract_auto_renewHint")}
            valuePropName="checked"
            className="pf-co-wide"
          >
            <Switch />
          </Form.Item>
        ) : null}
        {(
          [
            ["contract_notice_days", 0, 365],
            ["contract_next_year_from_day", 1, 31],
            ["contract_remind_first_days", 1, 365],
            ["contract_remind_last_days", 1, 365],
            ["contract_foreign_remind_days", 1, 365],
          ] as const
        ).map(([name, min, max]) =>
          shows(name) ? (
            <Form.Item key={name} name={name} label={t(`quote.${name}`)}>
              <InputNumber min={min} max={max} precision={0} {...NUMBER} />
            </Form.Item>
          ) : null,
        )}
        {shows("contract_foreign_by_agreement") ? (
          <Form.Item
            name="contract_foreign_by_agreement"
            label={t("quote.contract_foreign_by_agreement")}
            extra={t("quote.contract_foreign_by_agreementHint")}
            valuePropName="checked"
            className="pf-co-wide"
          >
            <Switch />
          </Form.Item>
        ) : null}
        {shows("contract_gating_kinds") ? (
          <Form.Item
            name="contract_gating_kinds"
            label={t("quote.contract_gating_kinds")}
            extra={t("quote.contract_gating_kindsHint")}
            className="pf-co-wide"
          >
            <Select
              mode="multiple"
              options={(["partner", "supply", "services"] as const).map((value) => ({
                value,
                label: t(`quote.gatingKind.${value}`),
              }))}
            />
          </Form.Item>
        ) : null}
        {shows("contract_expired_action") ? (
          <Form.Item
            name="contract_expired_action"
            label={t("quote.contract_expired_action")}
            extra={t("quote.contract_expired_actionHint")}
            className="pf-co-wide"
          >
            <Select
              options={(["block", "warn"] as const).map((value) => ({
                value,
                label: t(`quote.expiredAction.${value}`),
              }))}
            />
          </Form.Item>
        ) : null}
        {shows("default_warranty_months") ? (
          <Form.Item
            name="default_warranty_months"
            label={<UnitLabel label={t("quote.warranty")} />}
          >
            <InputNumber suffix={unitOf(t("quote.warranty"))} min={0} precision={0} {...NUMBER} />
          </Form.Item>
        ) : null}
        {shows("default_payment_terms") ? (
          <Form.Item
            name="default_payment_terms"
            label={t("quote.paymentTerms")}
            className="pf-co-wide"
          >
            <Input maxLength={255} />
          </Form.Item>
        ) : null}
        {shows("request_resolution") ? (
          <Form.Item
            name="request_resolution"
            label={t("quote.request_resolution")}
            extra={t("quote.request_resolutionHint")}
            className="pf-co-wide"
          >
            <Select
              options={(["always", "never"] as const).map((value) => ({
                value,
                label: t(`quote.resolution.${value}`),
              }))}
            />
          </Form.Item>
        ) : null}
        {shows("catalog_price_visibility") ? (
          <Form.Item name="catalog_price_visibility" label={t("quote.priceVisibility")}>
            <Select
              options={(["cabinet", "on_request"] as const).map((value) => ({
                value,
                label: t(`quote.visibility.${value}`),
              }))}
            />
          </Form.Item>
        ) : null}
        {shows("catalog_publish_threshold") ? (
          <Form.Item
            name="catalog_publish_threshold"
            label={<UnitLabel label={t("quote.threshold")} />}
            extra={t("quote.thresholdHint")}
          >
            <InputNumber
              suffix={unitOf(t("quote.threshold"))}
              min={1}
              max={100}
              precision={0}
              {...NUMBER}
            />
          </Form.Item>
        ) : null}
        {shows("catalog_require_mxik") ? (
          <Form.Item
            name="catalog_require_mxik"
            label={t("quote.requireMxik")}
            extra={t("quote.requireMxikHint")}
            valuePropName="checked"
            className="pf-co-wide"
          >
            <Switch />
          </Form.Item>
        ) : null}
        {shows("catalog_require_hs_imported") ? (
          <Form.Item
            name="catalog_require_hs_imported"
            label={t("quote.requireHs")}
            extra={t("quote.requireHsHint")}
            valuePropName="checked"
            className="pf-co-wide"
          >
            <Switch />
          </Form.Item>
        ) : null}
        {shows("fx_rate_max_age_days") ? (
          <Form.Item
            name="fx_rate_max_age_days"
            label={<UnitLabel label={t("quote.fxAge")} />}
            extra={t("quote.fxAgeHint")}
          >
            <InputNumber
              suffix={unitOf(t("quote.fxAge"))}
              min={1}
              max={90}
              precision={0}
              {...NUMBER}
            />
          </Form.Item>
        ) : null}
        {/* Сроки (задача «Н3c»): раньше были константами в коде */}
        {shows("offer_confirm_days") ? (
          <Form.Item name="offer_confirm_days" label={<UnitLabel label={t("quote.confirmDays")} />}>
            <InputNumber
              suffix={unitOf(t("quote.confirmDays"))}
              min={1}
              max={365}
              precision={0}
              {...NUMBER}
            />
          </Form.Item>
        ) : null}
        {shows("offer_expiring_days") ? (
          <Form.Item name="offer_expiring_days" label={t("quote.expiringDays")}>
            <InputNumber min={1} max={90} precision={0} {...NUMBER} />
          </Form.Item>
        ) : null}
        {shows("act_reminder_hours") ? (
          <Form.Item
            name="act_reminder_hours"
            label={<UnitLabel label={t("quote.actReminderHours")} />}
          >
            <InputNumber
              suffix={unitOf(t("quote.actReminderHours"))}
              min={1}
              max={720}
              precision={0}
              {...NUMBER}
            />
          </Form.Item>
        ) : null}
      </div>
      <SaveBlock
        label={t(`quote.groups.${group}.save`)}
        loading={update.isPending}
        disabled={isEmptyObject(changed)}
        error={update.error}
        note={t(`quote.groups.${group}.note`)}
        onDiscard={() => {
          form.resetFields();
          update.reset();
        }}
      />
      {group === "contracts" ? (
        <Button
          type="link"
          onClick={() => {
            setMore((v) => !v);
          }}
        >
          {t(more ? "quote.lessSettings" : "quote.moreSettings")}
        </Button>
      ) : null}
    </Form>
  );
}
