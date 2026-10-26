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
import { Field, LevelTag, PanelState, PanelTitle, ScrollTable } from "./parts";

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
    <ScrollTable label={t("spend.providers.title")}>
      <table className="pf-int-table" aria-label={t("spend.providers.title")}>
        <thead>
          <tr>
            <th scope="col">{t("spend.providers.provider")}</th>
            <th scope="col" className="num">
              {t("spend.providers.spent")}
            </th>
            <th scope="col" className="num">
              {t("spend.providers.limit")}
            </th>
            <th scope="col">{t("spend.providers.state")}</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((provider) => {
            const { level, ratio } = budgetLevel(provider);
            return (
              <tr key={provider.provider}>
                <th scope="row">{provider.provider}</th>
                <td className="num">{usd(provider.spent_usd)}</td>
                <td className="num">
                  {provider.limit_usd > 0 ? usd(provider.limit_usd) : t("spend.providers.noLimit")}
                </td>
                <td>
                  {level === "off" ? (
                    t("spend.providers.noLimit")
                  ) : (
                    <>
                      <LevelTag level={level} />{" "}
                      <span className="pf-hint">
                        {percent((ratio ?? 0) * 100, { fractionDigits: 0 })}
                      </span>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </ScrollTable>
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
              <ScrollTable label={t("spend.series.title")}>
                <table className="pf-int-table" aria-label={t("spend.series.title")}>
                  <thead>
                    <tr>
                      <th scope="col">{t("spend.series.day")}</th>
                      <th scope="col" className="num">
                        {t("spend.series.work")}
                      </th>
                      <th scope="col" className="num">
                        {t("spend.series.test")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.series.slice(-10).map((row) => (
                      <tr key={row.day}>
                        <th scope="row">{date(row.day)}</th>
                        <td className="num">{usd(row.work_usd)}</td>
                        <td className="num">{usd(row.test_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollTable>
            ) : null}
            {report.by_purpose.length > 0 ? (
              <ScrollTable label={t("spend.purpose.title")}>
                <table className="pf-int-table" aria-label={t("spend.purpose.title")}>
                  <thead>
                    <tr>
                      <th scope="col">{t("spend.purpose.key")}</th>
                      <th scope="col" className="num">
                        {t("spend.purpose.calls")}
                      </th>
                      <th scope="col" className="num">
                        {t("spend.purpose.cost")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.by_purpose.map((row) => (
                      <tr key={row.key}>
                        <th scope="row">{row.key}</th>
                        <td className="num">{number(row.calls)}</td>
                        <td className="num">{usd(row.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollTable>
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
        <ScrollTable label={t("spend.ensemble.systems")}>
          <table className="pf-int-table" aria-label={t("spend.ensemble.systems")}>
            <thead>
              <tr>
                <th scope="col">{t("spend.ensemble.system")}</th>
                <th scope="col" className="num">
                  {t("spend.ensemble.budget")}
                </th>
                <th scope="col" className="num">
                  {t("spend.ensemble.today")}
                </th>
                <th scope="col">{t("spend.ensemble.state")}</th>
              </tr>
            </thead>
            <tbody>
              {report.systems.map((system) => (
                <tr key={system.system}>
                  <th scope="row">{system.system}</th>
                  <td className="num">
                    {system.daily_usd > 0 ? usd(system.daily_usd) : t("spend.providers.noLimit")}
                  </td>
                  <td className="num">{usd(system.today_usd)}</td>
                  <td>
                    {!system.connected ? (
                      <LevelTag level="off" />
                    ) : system.over_today ? (
                      <LevelTag level="fail" />
                    ) : system.days_over > 0 ? (
                      <LevelTag level="warn" />
                    ) : (
                      <LevelTag level="ok" />
                    )}{" "}
                    <span className="pf-hint">
                      {!system.connected
                        ? t("spend.ensemble.notConnected")
                        : t("spend.ensemble.daysOver", { count: system.days_over })}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      ) : null}
      {report.rows.length > 0 ? (
        <ScrollTable label={t("spend.ensemble.rows")}>
          <table className="pf-int-table" aria-label={t("spend.ensemble.rows")}>
            <thead>
              <tr>
                <th scope="col">{t(`spend.ensemble.group.${report.group}`)}</th>
                <th scope="col" className="num">
                  {t("spend.ensemble.calls")}
                </th>
                <th scope="col" className="num">
                  {t("spend.ensemble.tokens")}
                </th>
                <th scope="col" className="num">
                  {t("spend.ensemble.cost")}
                </th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr key={row.key}>
                  <th scope="row">{report.group === "day" ? date(row.key) : row.key}</th>
                  <td className="num">{number(row.calls)}</td>
                  <td className="num">{number(row.input_tokens + row.output_tokens)}</td>
                  <td className="num">{usd(row.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
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
export function SpendPanel() {
  const { t } = useTranslation("integrations");
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.spend.title")}</PanelTitle>
      <BotSpend />
      <EnsembleSpend />
    </div>
  );
}
