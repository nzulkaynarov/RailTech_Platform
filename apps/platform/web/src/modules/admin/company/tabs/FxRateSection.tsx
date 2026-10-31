import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input } from "antd";
import type { TableColumnsType } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { FxRate, FxRateJournalEntry } from "../../../../shared/api/generated/model";
import {
  getGetFxRateQueryKey,
  getGetPlatformSettingsQueryKey,
  useCreateFxRate,
  useGetFxRate,
} from "../../../../shared/api/generated/platform-bff";
import { companyDayKey } from "../../../../shared/lib/dates";
import { useFormat } from "../../../../shared/lib/useFormat";
import { Consequence } from "../../../../shared/ui/Consequence";
import { DateField } from "../../../../shared/ui/DateField";
import { DefinitionList } from "../../../../shared/ui/DefinitionList";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { ListTable, QueryGate, ReadOnlyFence } from "../common";
import { companyErrorText, errorFields } from "../errors";
import { useReadOnly } from "../useReadOnly";

interface Values {
  rate_date: string;
  rate_to_uzs: string;
}

/** Курс — положительное число не более чем с 6 знаками после запятой (как в ERP); запятая принимается как точка. */
const RATE = /^[0-9]+(\.[0-9]{1,6})?$/;
const normalize = (value: string) => value.trim().replace(",", ".");

function decimals(rate: string) {
  const fraction = rate.split(".")[1];
  return Math.min(Math.max(fraction?.length ?? 0, 2), 6);
}

/**
 * Курс USD → UZS на вкладке «Платформа» (W13C-F6): текущий курс с датой и источником и ручной ввод курса на дату — на
 * случай, если автозагрузка курса ЦБ (`erp-beat`) не сработала. Ниже — журнал последних записей: кто, когда и что ввёл;
 * без права `settings.edit` в ERP (`journal_available = false`) журнала нет — в нём имена и почта коллег.
 */
export function FxRateSection() {
  const { t } = useTranslation("company");
  const query = useGetFxRate();
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="pf-co-fx">
      <h3 id={headingId} className="pf-co-title" style={{ fontSize: 16, lineHeight: "24px" }}>
        {t("platform.fx.title")}
      </h3>
      <QueryGate query={query}>
        {(overview) => (
          <>
            <CurrentRate current={overview.current} maxAgeDays={overview.max_age_days} />
            <FxForm />
            {overview.journal_available ? <FxJournal rows={overview.journal} /> : null}
          </>
        )}
      </QueryGate>
    </section>
  );
}

function CurrentRate({ current, maxAgeDays }: { current: FxRate | null; maxAgeDays: number }) {
  const { t } = useTranslation("company");
  const { number, date } = useFormat();
  if (current === null) {
    return (
      <Alert
        type="warning"
        showIcon
        role="status"
        message={t("platform.fx.missing", { days: maxAgeDays })}
      />
    );
  }
  return (
    <DefinitionList
      items={[
        {
          label: t("platform.fx.current"),
          value: `1 USD = ${number(current.rate_to_uzs, { fractionDigits: decimals(current.rate_to_uzs) })} ${t("platform.currencyUzs")}`,
        },
        { label: t("platform.fx.date"), value: date(current.rate_date) },
        { label: t("platform.fx.source"), value: <SourceTag source={current.source} /> },
      ]}
    />
  );
}

function SourceTag({ source }: { source: "auto" | "manual" }) {
  const { t } = useTranslation("company");
  return (
    <StatusTag tone={source === "manual" ? "gold" : "blue"}>
      {t(`platform.fx.sources.${source}`)}
    </StatusTag>
  );
}

function FxForm() {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const readOnly = useReadOnly();
  const [form] = Form.useForm<Values>();
  const today = companyDayKey(new Date()) ?? "";
  const create = useCreateFxRate({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetFxRateQueryKey(), next);
        void queryClient.invalidateQueries({ queryKey: getGetPlatformSettingsQueryKey() });
        form.setFieldValue("rate_to_uzs", "");
        void message.success(t("platform.fx.saved"));
      },
    },
  });
  const fieldFailed = errorFields(create.error).some(
    (name) => name === "rate_to_uzs" || name === "rate_date",
  );
  return (
    <ReadOnlyFence block>
      <Form<Values>
        form={form}
        layout="vertical"
        initialValues={{ rate_date: today, rate_to_uzs: "" }}
        aria-label={t("platform.fx.formLabel")}
        onFinish={(values) => {
          create.mutate(
            { data: { rate_date: values.rate_date, rate_to_uzs: normalize(values.rate_to_uzs) } },
            {
              onError: (error) => {
                const reason = companyErrorText(t, error);
                form.setFields(
                  errorFields(error)
                    .filter((name) => name === "rate_to_uzs" || name === "rate_date")
                    .map((name) => ({ name, errors: [reason] })),
                );
              },
            },
          );
        }}
      >
        <div className="pf-co-grid">
          <Form.Item
            name="rate_date"
            label={t("platform.fx.dateField")}
            extra={t("platform.fx.dateHint")}
            rules={[
              { required: true, message: t("required") },
              {
                validator: (_rule, value: string) =>
                  !value || value <= today
                    ? Promise.resolve()
                    : Promise.reject(new Error(t("errors.reason.fx_rate_date_in_future"))),
              },
            ]}
          >
            <DateField max={today} />
          </Form.Item>
          <Form.Item
            name="rate_to_uzs"
            label={t("platform.fx.rateField")}
            extra={t("platform.fx.rateHint")}
            rules={[
              { required: true, message: t("required") },
              {
                validator: (_rule, value: string) => {
                  const rate = normalize(value);
                  if (!rate) return Promise.resolve();
                  return RATE.test(rate) && Number(rate) > 0 && Number(rate) < 1_000_000_000
                    ? Promise.resolve()
                    : Promise.reject(new Error(t("errors.reason.fx_rate_invalid")));
                },
              },
            ]}
          >
            <Input inputMode="decimal" autoComplete="off" />
          </Form.Item>
        </div>
        <div className="pf-co-save">
          {create.error && !fieldFailed ? (
            <Alert type="error" showIcon role="alert" message={companyErrorText(t, create.error)} />
          ) : null}
          <div>
            <Button htmlType="submit" loading={create.isPending} disabled={readOnly}>
              {t("platform.fx.save")}
            </Button>
          </div>
          <Consequence
            items={[
              t("platform.fx.consequence.replace"),
              t("platform.fx.consequence.quotes"),
              t("platform.fx.consequence.older"),
            ]}
          />
        </div>
      </Form>
    </ReadOnlyFence>
  );
}

function FxJournal({ rows }: { rows: readonly FxRateJournalEntry[] }) {
  const { t } = useTranslation("company");
  const { number, date } = useFormat();
  const columns: TableColumnsType<FxRateJournalEntry> = [
    {
      title: t("platform.fx.journal.date"),
      key: "rate_date",
      render: (_v, row) => date(row.rate_date),
    },
    {
      title: t("platform.fx.journal.rate"),
      key: "rate",
      align: "right",
      render: (_v, row) => number(row.rate_to_uzs, { fractionDigits: decimals(row.rate_to_uzs) }),
    },
    {
      title: t("platform.fx.journal.event"),
      key: "kind",
      render: (_v, row) =>
        row.kind === "manual" ? (
          <StatusTag tone="gold">{t("platform.fx.journal.manual")}</StatusTag>
        ) : (
          <StatusTag tone="default">{t("platform.fx.journal.autoSkipped")}</StatusTag>
        ),
    },
    {
      title: t("platform.fx.journal.before"),
      key: "before",
      render: (_v, row) =>
        row.previous_rate_to_uzs === null
          ? t("platform.fx.journal.none")
          : t("platform.fx.journal.was", {
              rate: number(row.previous_rate_to_uzs, {
                fractionDigits: decimals(row.previous_rate_to_uzs),
              }),
              source: t(`platform.fx.sources.${row.previous_source ?? "auto"}`),
            }),
    },
    {
      title: t("platform.fx.journal.who"),
      key: "who",
      render: (_v, row) => row.entered_by ?? t("platform.fx.journal.system"),
    },
    {
      title: t("platform.fx.journal.when"),
      key: "when",
      render: (_v, row) => date(row.entered_at, "datetime"),
    },
  ];
  return (
    <>
      <h4 className="pf-co-title" style={{ fontSize: 14, lineHeight: "22px" }}>
        {t("platform.fx.journal.title")}
      </h4>
      <ListTable<FxRateJournalEntry>
        label={t("platform.fx.journal.title")}
        columns={columns}
        data={rows}
        rowKey={(row) => row.id}
        empty={{
          title: t("platform.fx.journal.emptyTitle"),
          text: t("platform.fx.journal.emptyText"),
        }}
      />
    </>
  );
}
