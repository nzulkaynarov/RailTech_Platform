import { App, Button, Card, Form, Input, InputNumber } from "antd";
import dayjs from "dayjs";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { CalcSheet, CalcTerms, CalcTermsPatch } from "../../../shared/api/generated/model";
import { useUpdateCalcTerms } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { calcRef, useApplySheet, useErrorText } from "./api";

interface Values {
  payment_terms?: string;
  valid_until?: string | null;
  delivery_days?: number | null;
  delivery_note?: string;
}

const EMPTY: CalcTerms = {
  payment_terms: null,
  valid_until: null,
  delivery_days: null,
  delivery_days_lines: 0,
  delivery_note: null,
};

/**
 * Условия КП (план 0.5, FR-16): оплата, срок действия и срок поставки — то, что клиент увидит в КП, PDF и кабинете.
 * Сводка под строками расчёта; правка — короткая форма в боковом окне (platform-frontend.md §4.1a).
 */
export function TermsCard({
  sheet,
  editable,
  onEdit,
}: {
  sheet: CalcSheet;
  editable: boolean;
  onEdit: () => void;
}) {
  const { t } = useTranslation("calc");
  const { date } = useFormat();
  const terms = sheet.quote?.terms ?? EMPTY;
  const delivery =
    terms.delivery_days === null
      ? t("terms.byLines", { count: terms.delivery_days_lines })
      : t("terms.days", { count: terms.delivery_days });
  return (
    <Card
      size="small"
      title={<h2 className="pf-calc-title">{t("terms.title")}</h2>}
      extra={
        editable && sheet.rights.build ? <Button onClick={onEdit}>{t("terms.edit")}</Button> : null
      }
    >
      <DefinitionList
        items={[
          { label: t("terms.payment"), value: terms.payment_terms },
          {
            label: t("terms.validUntil"),
            value: terms.valid_until ? date(terms.valid_until) : null,
          },
          {
            label: t("terms.delivery"),
            value: [delivery, terms.delivery_note].filter(Boolean).join(" · "),
          },
        ]}
      />
    </Card>
  );
}

export function TermsForm({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { t } = useTranslation("calc");
  const titleId = useId();
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const [form] = Form.useForm<Values>();
  const terms = sheet.quote?.terms ?? EMPTY;
  const save = useUpdateCalcTerms({
    mutation: {
      onSuccess: (next) => {
        apply(next);
        onClose();
      },
      onError: (error) => {
        const fields = error instanceof ApiError ? error.details.fields : undefined;
        if (Array.isArray(fields) && fields.includes("valid_until")) {
          form.setFields([{ name: "valid_until", errors: [t("terms.validUntilPast")] }]);
          return;
        }
        void message.error(errorText(error));
      },
    },
  });
  return (
    <section className="pf-calc-panel-form" aria-labelledby={titleId}>
      <h3 className="pf-fp-title" id={titleId}>
        {t("terms.title")}
      </h3>
      <Form<Values>
        form={form}
        layout="vertical"
        initialValues={{
          payment_terms: terms.payment_terms ?? "",
          valid_until: terms.valid_until,
          delivery_days: terms.delivery_days,
          delivery_note: terms.delivery_note ?? "",
        }}
        onFinish={(values) => {
          const data: CalcTermsPatch = {
            payment_terms: values.payment_terms?.trim() ?? "",
            valid_until: values.valid_until ?? null,
            delivery_days: values.delivery_days ?? null,
            delivery_note: values.delivery_note?.trim() ?? "",
          };
          save.mutate({ number: calcRef(sheet.number), data });
        }}
      >
        <Form.Item name="payment_terms" label={t("terms.payment")}>
          <Input maxLength={255} />
        </Form.Item>
        <Form.Item name="valid_until" label={t("terms.validUntil")}>
          <DateField min={dayjs().format("YYYY-MM-DD")} />
        </Form.Item>
        <Form.Item
          name="delivery_days"
          label={t("terms.deliveryDays")}
          extra={t("terms.byLines", { count: terms.delivery_days_lines })}
        >
          <InputNumber min={0} max={3650} precision={0} />
        </Form.Item>
        <Form.Item name="delivery_note" label={t("terms.note")}>
          <Input maxLength={255} />
        </Form.Item>
        <div className="pf-calc-panel-actions">
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            {t("terms.save")}
          </Button>
          <Button onClick={onClose}>{t("add.cancel")}</Button>
        </div>
      </Form>
    </section>
  );
}
