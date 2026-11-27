import { Select } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AiSpendReport,
  GetAiSpendReportGroup,
  IntegrationStatus,
  ProviderToday,
  SpendReport,
} from "../../../shared/api/generated/model";
import { useGetAiSpendReport, useGetSpendReport } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Field, LevelTag, PanelState, PanelTitle, ReportTable } from "./parts";

const PERIODS = [7, 30, 90] as const;
const GROUPS: readonly GetAiSpendReportGroup[] = ["day", "system", "feature", "model"];
const WARN_RATIO = 0.8;

type Usd = (value: number, digits?: number) => string;

function useUsd(): Usd {
  const { money } = useFormat();
  return (value, digits = 2) => money(value, { currency: "USD", fractionDigits: digits });
}

function Tiles({ items }: { items: readonly { label: string; value: string }[] }) {
  return (
    <dl className="pf-int-tiles">
      {items.map((item) => (
        <div key={item.label} className="pf-int-tile">
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function budgetLevel(provider: ProviderToday): { level: IntegrationStatus; ratio: number | null } {
  if (provider.limit_usd <= 0) return { level: "off", ratio: null };
  const ratio = provider.spent_usd / provider.limit_usd;
  return { level: ratio >= 1 ? "fail" : ratio >= WARN_RATIO ? "warn" : "ok", ratio };
}

function ProvidersTable({ providers }: { providers: SpendReport["providers"] }) {
  const { t } = useTranslation("integrations");
  const { percent } = useFormat();
  const usd = useUsd();
  if (providers.length === 0) return null;
  return (
    <ReportTable<ProviderToday>
      id="providers"
      label={t("spend.providers.title")}
      rows={providers}
      rowKey={(provider) => provider.provider}
      columns={[
        {
          id: "provider",
          header: t("spend.providers.provider"),
          width: null,
          rowHeader: true,
          cell: (provider) => provider.provider,
        },
        {
          id: "spent",
          header: t("spend.providers.spent"),
          width: 120,
          numeric: true,
          cell: (provider) => usd(provider.spent_usd),
        },
        {
          id: "limit",
          header: t("spend.providers.limit"),
          width: 120,
          numeric: true,
          cell: (provider) =>
            provider.limit_usd > 0 ? usd(provider.limit_usd) : t("spend.providers.noLimit"),
        },
        {
          id: "state",
          header: t("spend.providers.state"),
          width: 180,
          cell: (provider) => {
            const { level, ratio } = budgetLevel(provider);
            return level === "off" ? (
              t("spend.providers.noLimit")
            ) : (
              <>
                <LevelTag level={level} />{" "}
                <span className="pf-hint">
                  {percent((ratio ?? 0) * 100, { fractionDigits: 0 })}
                </span>
              </>
            );
          },
        },
      ]}
    />
  );
}

function BotSpend() {
  const { t } = useTranslation("integrations");
  const { date, number } = useFormat();
  const usd = useUsd();
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const query = useGetSpendReport({ days });
  return (
    <section className="pf-int-block" aria-labelledby="spend-bot-title">
      <h4 id="spend-bot-title">{t("spend.bot.title")}</h4>
      <p className="pf-int-sub">{t("spend.bot.text")}</p>
      <Field id="spend-days" label={t("spend.period")}>
        <Select
          id="spend-days"
          value={days}
          style={{ maxWidth: 240 }}
          options={PERIODS.map((value) => ({ value, label: t("spend.days", { count: value }) }))}
          onChange={setDays}
        />
      </Field>
      <PanelState query={query}>
        {(report) => (
          <>
            <Tiles
              items={[
                { label: t("spend.tiles.today"), value: usd(report.today_usd) },
                {
                  label: t("spend.tiles.budget"),
                  value:
                    report.daily_usd > 0 ? usd(report.daily_usd) : t("spend.providers.noLimit"),
                },
                { label: t("spend.tiles.total"), value: usd(report.total_usd) },
                { label: t("spend.tiles.leads"), value: number(report.leads) },
                { label: t("spend.tiles.perLead"), value: usd(report.avg_per_lead_usd, 3) },
              ]}
            />
            <ProvidersTable providers={report.providers} />
            {report.series.length > 0 ? (
              <ReportTable<SpendReport["series"][number]>
                id="series"
                label={t("spend.series.title")}
                rows={report.series.slice(-10)}
                rowKey={(row) => row.day}
                columns={[
                  {
                    id: "day",
                    header: t("spend.series.day"),
                    width: null,
                    rowHeader: true,
                    cell: (row) => date(row.day),
                  },
                  {
                    id: "work",
                    header: t("spend.series.work"),
                    width: 140,
                    numeric: true,
                    cell: (row) => usd(row.work_usd),
                  },
                  {
                    id: "test",
                    header: t("spend.series.test"),
                    width: 140,
                    numeric: true,
                    cell: (row) => usd(row.test_usd),
                  },
                ]}
              />
            ) : null}
            {report.by_purpose.length > 0 ? (
              <ReportTable<SpendReport["by_purpose"][number]>
                id="purpose"
                label={t("spend.purpose.title")}
                rows={report.by_purpose}
                rowKey={(row) => row.key}
                columns={[
                  {
                    id: "key",
                    header: t("spend.purpose.key"),
                    width: null,
                    rowHeader: true,
                    cell: (row) => row.key,
                  },
                  {
                    id: "calls",
                    header: t("spend.purpose.calls"),
                    width: 120,
                    numeric: true,
                    cell: (row) => number(row.calls),
                  },
                  {
                    id: "cost",
                    header: t("spend.purpose.cost"),
                    width: 140,
                    numeric: true,
                    cell: (row) => usd(row.cost_usd),
                  },
                ]}
              />
            ) : null}
          </>
        )}
      </PanelState>
    </section>
  );
}

function EnsembleBody({ report }: { report: AiSpendReport }) {
  const { t } = useTranslation("integrations");
  const { date, number } = useFormat();
  const usd = useUsd();
  return (
    <>
      <p className="pf-int-sub">
        {t("spend.ensemble.range", {
          from: date(report.date_from),
          to: date(report.date_to),
          zone: report.timezone,
        })}
      </p>
      <Tiles
        items={[
          { label: t("spend.ensemble.calls"), value: number(report.totals.calls) },
          { label: t("spend.ensemble.failed"), value: number(report.totals.failed_calls) },
          { label: t("spend.ensemble.fallback"), value: number(report.totals.fallback_calls) },
          { label: t("spend.ensemble.cost"), value: usd(report.totals.cost_usd) },
        ]}
      />
      {report.truncated ? <p className="pf-int-sub">{t("spend.ensemble.truncated")}</p> : null}
      {report.systems.length > 0 ? (
        <ReportTable<AiSpendReport["systems"][number]>
          id="systems"
          label={t("spend.ensemble.systems")}
          rows={report.systems}
          rowKey={(system) => system.system}
          columns={[
            {
              id: "system",
              header: t("spend.ensemble.system"),
              width: null,
              rowHeader: true,
              cell: (system) => system.system,
            },
            {
              id: "budget",
              header: t("spend.ensemble.budget"),
              width: 130,
              numeric: true,
              cell: (system) =>
                system.daily_usd > 0 ? usd(system.daily_usd) : t("spend.providers.noLimit"),
            },
            {
              id: "today",
              header: t("spend.ensemble.today"),
              width: 120,
              numeric: true,
              cell: (system) => usd(system.today_usd),
            },
            {
              id: "state",
              header: t("spend.ensemble.state"),
              width: 240,
              cell: (system) => (
                <>
                  <LevelTag level={systemLevel(system)} />{" "}
                  <span className="pf-hint">
                    {!system.connected
                      ? t("spend.ensemble.notConnected")
                      : t("spend.ensemble.daysOver", { count: system.days_over })}
                  </span>
                </>
              ),
            },
          ]}
        />
      ) : null}
      {report.rows.length > 0 ? (
        <ReportTable<AiSpendReport["rows"][number]>
          id="ensemble"
          label={t("spend.ensemble.rows")}
          rows={report.rows}
          rowKey={(row) => row.key}
          columns={[
            {
              id: "key",
              header: t(`spend.ensemble.group.${report.group}`),
              width: null,
              rowHeader: true,
              cell: (row) => (report.group === "day" ? date(row.key) : row.key),
            },
            {
              id: "calls",
              header: t("spend.ensemble.calls"),
              width: 110,
              numeric: true,
              cell: (row) => number(row.calls),
            },
            {
              id: "tokens",
              header: t("spend.ensemble.tokens"),
              width: 130,
              numeric: true,
              cell: (row) => number(row.input_tokens + row.output_tokens),
            },
            {
              id: "cost",
              header: t("spend.ensemble.cost"),
              width: 120,
              numeric: true,
              cell: (row) => usd(row.cost_usd),
            },
          ]}
        />
      ) : null}
      {report.overruns.length > 0 ? (
        <ul className="pf-int-list" aria-label={t("spend.ensemble.overruns")}>
          {report.overruns.map((row) => (
            <li key={`${row.system}-${row.day}`}>
              <span className="pf-int-item-title">
                {t("spend.ensemble.overrun", {
                  system: row.system,
                  day: date(row.day),
                  cost: usd(row.cost_usd),
                  limit: usd(row.daily_usd),
                })}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function EnsembleSpend() {
  const { t } = useTranslation("integrations");
  const [group, setGroup] = useState<GetAiSpendReportGroup>("day");
  const params = useMemo(() => ({ group }), [group]);
  const query = useGetAiSpendReport(params);
  return (
    <section className="pf-int-block" aria-labelledby="spend-ai-title">
      <h4 id="spend-ai-title">{t("spend.ensemble.title")}</h4>
      <p className="pf-int-sub">{t("spend.ensemble.text")}</p>
      <Field id="spend-group" label={t("spend.ensemble.groupBy")}>
        <Select
          id="spend-group"
          value={group}
          style={{ maxWidth: 240 }}
          options={GROUPS.map((value) => ({ value, label: t(`spend.ensemble.group.${value}`) }))}
          onChange={setGroup}
        />
      </Field>
      <PanelState query={query}>{(report) => <EnsembleBody report={report} />}</PanelState>
    </section>
  );
}

/** Карточка «Расходы»: бот (`/spend`) и весь ансамбль (`/admin/ai-spend`); директору — на чтение. */
/** Уровень строки «Системы» — из данных отчёта (не подключена, превышение сегодня, дни превышения), а не литералом. */
function systemLevel(system: {
  connected: boolean;
  over_today: boolean;
  days_over: number;
}): IntegrationStatus {
  if (!system.connected) return "off";
  if (system.over_today) return "fail";
  return system.days_over > 0 ? "warn" : "ok";
}

export function SpendPanel({ titled = true }: { titled?: boolean }) {
  const { t } = useTranslation("integrations");
  return (
    <div className="pf-panel-stack">
      {titled ? <PanelTitle>{t("cards.spend.title")}</PanelTitle> : null}
      <BotSpend />
      <EnsembleSpend />
    </div>
  );
}
