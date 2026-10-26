import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Form, Input, InputNumber, Select } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { QuoteDefaults } from "../../../../shared/api/generated/model";
import {
  getGetQuoteDefaultsQueryKey,
  useGetQuoteDefaults,
  useListReferenceItems,
  useUpdateQuoteDefaults,
} from "../../../../shared/api/generated/platform-bff";
import { QueryGate, SaveBlock, TabHeader } from "../common";
import { changedFields, codeLabel, isEmptyObject } from "../diff";
import { errorFields } from "../errors";

type Values = Omit<QuoteDefaults, never>;

const MARGINS = ["default_margin_percent", "min_margin_percent", "target_margin_percent"] as const;

/** Условия КП по умолчанию (ERP `companies/{id}/settings`): валюта, базис, НДС, маржа, сроки, политика каталога. */
export function QuoteTab() {
  const { t } = useTranslation("company");
  const query = useGetQuoteDefaults();
  return (
    <div className="pf-co-body">
      <TabHeader title={t("quote.title")} hint={t("quote.hint")} />
      <QueryGate query={query}>
        {(defaults) => <QuoteForm key={JSON.stringify(defaults)} defaults={defaults} />}
      </QueryGate>
    </div>
  );
}

const NUMBER = { style: { width: "100%" } } as const;

function QuoteForm({ defaults }: { defaults: QuoteDefaults }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const initial = useMemo<Values>(() => ({ ...defaults }), [defaults]);
  const watched = Form.useWatch([], form);
  const changed = changedFields(initial, watched);
  const currencies = useListReferenceItems("currencies");
  const bases = useListReferenceItems("delivery-basis");
  // Без права на группу `cost_margin` BFF не присылает поля маржи совсем.
  const marginsVisible = defaults.default_margin_percent !== undefined;

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
      {!marginsVisible ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t("quote.marginHidden")}
        />
      ) : null}
      <div className="pf-co-grid">
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
        <Form.Item
          name="default_delivery_basis"
          label={t("quote.basis")}
          extra={t("quote.basisHint")}
        >
          <Select allowClear loading={bases.isPending} options={active(bases.data?.items)} />
        </Form.Item>
        <Form.Item name="default_vat_rate" label={t("quote.vat")}>
          <InputNumber stringMode min="0" max="100" step="0.5" {...NUMBER} />
        </Form.Item>
        {marginsVisible
          ? MARGINS.map((name) => (
              <Form.Item key={name} name={name} label={t(`quote.${name}`)}>
                <InputNumber stringMode min="0" max="100" step="0.5" {...NUMBER} />
              </Form.Item>
            ))
          : null}
        <Form.Item name="default_offer_validity_days" label={t("quote.validity")}>
          <InputNumber min={0} precision={0} {...NUMBER} />
        </Form.Item>
        <Form.Item name="payment_terms_days" label={t("quote.paymentDays")}>
          <InputNumber min={0} precision={0} {...NUMBER} />
        </Form.Item>
        <Form.Item name="default_warranty_months" label={t("quote.warranty")}>
          <InputNumber min={0} precision={0} {...NUMBER} />
        </Form.Item>
        <Form.Item
          name="default_payment_terms"
          label={t("quote.paymentTerms")}
          className="pf-co-wide"
        >
          <Input maxLength={255} />
        </Form.Item>
        <Form.Item name="catalog_price_visibility" label={t("quote.priceVisibility")}>
          <Select
            options={(["cabinet", "on_request"] as const).map((value) => ({
              value,
              label: t(`quote.visibility.${value}`),
            }))}
          />
        </Form.Item>
        <Form.Item
          name="catalog_publish_threshold"
          label={t("quote.threshold")}
          extra={t("quote.thresholdHint")}
        >
          <InputNumber min={1} max={100} precision={0} {...NUMBER} />
        </Form.Item>
        <Form.Item
          name="fx_rate_max_age_days"
          label={t("quote.fxAge")}
          extra={t("quote.fxAgeHint")}
        >
          <InputNumber min={1} max={90} precision={0} {...NUMBER} />
        </Form.Item>
      </div>
      <SaveBlock
        label={t("quote.save")}
        loading={update.isPending}
        disabled={isEmptyObject(changed)}
        error={update.error}
        consequence={[t("quote.consequence.new"), t("quote.consequence.issued")]}
      />
    </Form>
  );
}
