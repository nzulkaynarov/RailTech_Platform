import { Button, Card, Form, InputNumber, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ResolveSignersParams } from "../../../shared/api/generated/model";
import {
  useListDictionaryItems,
  useResolveSigners,
} from "../../../shared/api/generated/platform-bff";
import { companyToday } from "../../../shared/lib/dates";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { localName } from "../../eds/dictionaries";
import { CURRENCIES } from "./model";

interface Values {
  kind: string | undefined;
  amount: number | null;
  currency: string;
  date: string;
}

/**
 * Проверка правил: «кто вправе подписать вид X на сумму Y на дату D» — тот же подбор, что у шага «Подписать» (ADR-0024 п. 3).
 * Показывает, кто подпишет, и по-русски — почему остальные нет (лимит, срок, отзыв, замещение без собственного полномочия).
 */
export function ResolveCheck() {
  const { t, i18n } = useTranslation("signing");
  const format = useFormat();
  const [form] = Form.useForm<Values>();
  const [ask, setAsk] = useState<ResolveSignersParams | null>(null);
  const kinds = useListDictionaryItems("signing-kinds", undefined, {
    query: { staleTime: 5 * 60_000 },
  });
  const result = useResolveSigners(ask ?? { kind: "" }, { query: { enabled: ask !== null } });
  const data = ask ? result.data : undefined;
  return (
    <Card title={t("check.title")} className="pf-sign-check">
      <p className="pf-hint">{t("check.hint")}</p>
      <Form<Values>
        form={form}
        layout="vertical"
        className="pf-sign-check-form"
        initialValues={{
          kind: undefined,
          amount: null,
          currency: CURRENCIES[0],
          date: companyToday(),
        }}
        onFinish={(v) => {
          if (!v.kind) return;
          setAsk({
            kind: v.kind,
            ...(v.amount && v.amount > 0
              ? { amount: v.amount.toFixed(2), currency: v.currency }
              : {}),
            ...(v.date ? { on_date: v.date } : {}),
          });
        }}
      >
        <Form.Item
          name="kind"
          label={t("check.kind")}
          rules={[
            {
              // У выбора правило `required` ставит `aria-required` на контейнер без роли (axe): проверка своя.
              validator: (_: unknown, value: unknown) =>
                value ? Promise.resolve() : Promise.reject(new Error(t("form.required"))),
            },
          ]}
        >
          <Select
            options={(kinds.data?.items ?? []).map((item) => ({
              value: item.code,
              label: localName(item.name, i18n.language),
            }))}
          />
        </Form.Item>
        <Form.Item name="amount" label={t("check.amount")}>
          <InputNumber min={0} precision={2} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="currency" label={t("check.currency")}>
          <Select
            options={CURRENCIES.map((code) => ({ value: code, label: format.currency(code) }))}
          />
        </Form.Item>
        <Form.Item name="date" label={t("check.date")}>
          <DateField allowClear={false} />
        </Form.Item>
        <Form.Item label=" " colon={false}>
          <Button htmlType="submit" loading={result.isFetching}>
            {t("check.run")}
          </Button>
        </Form.Item>
      </Form>
      {data ? (
        <div className="pf-sign-result" aria-live="polite">
          <h3 className="pf-sign-h3">{data.resolved ? t("check.result") : t("check.none")}</h3>
          {data.candidates.length > 0 ? (
            <ul>
              {data.candidates.map((c) => (
                <li key={c.signer.id}>
                  <b>{c.signer.name}</b>
                  {c.acting_for.length > 0
                    ? ` · ${t("check.actingFor", { names: c.acting_for.map((p) => p.name).join(", ") })}`
                    : ""}
                </li>
              ))}
            </ul>
          ) : null}
          <h3 className="pf-sign-h3">{t("check.why")}</h3>
          <ul>
            {data.explanation.map((step, index) => (
              <li key={index}>{step.text}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}
