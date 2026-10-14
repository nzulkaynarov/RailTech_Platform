import { Card, Segmented, Skeleton, Typography } from "antd";
import { lazy, Suspense, useState } from "react";

import { useSpend } from "../../api/spendQueries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { UrlTabs } from "../../components/UrlTabs";
import { PROVIDER_CONSOLES } from "../../domain/spend";
import { t } from "../../i18n/ru";
import { AiSpendPanel } from "./AiSpendPanel";
import "../admin.css";

const PERIODS = [7, 30, 90];

/** Графики и таблицы — отдельным чанком (`@ant-design/plots` не попадает в другие страницы). */
const SpendCharts = lazy(() => import("./SpendCharts"));

/** Вкладка «CRM подробно»: учёт CRM (`llm_usage`) — лимиты провайдеров, работа/тесты, лиды. */
function CrmSpend({ days }: { days: number }) {
  const query = useSpend(days);
  const report = query.data;
  return (
    <PageState query={query}>
      {report && (
        <>
          <Suspense fallback={<Skeleton active aria-label={t.charts.loading} />}>
            <SpendCharts report={report} />
          </Suspense>
          {report.total_usd > 0 ? null : (
            <Card size="small">
              <Typography.Text strong>{t.spend.empty}</Typography.Text>
              <Typography.Paragraph type="secondary">{t.spend.emptyHint}</Typography.Paragraph>
            </Card>
          )}
          <Typography.Paragraph type="secondary">
            {t.spend.consoles}{" "}
            {PROVIDER_CONSOLES.map((c, i) => (
              <span key={c.href}>
                {i > 0 && " · "}
                <Typography.Link href={c.href} target="_blank" rel="noreferrer">
                  {c.label}
                </Typography.Link>
              </span>
            ))}
          </Typography.Paragraph>
        </>
      )}
    </PageState>
  );
}

/**
 * «Расходы» (админ): «Ансамбль» — журнал шлюза LiteLLM по системам CRM и ERP, функциям и моделям
 * с бюджетом на день по системе (M3-CRM-09); «CRM подробно» — учёт CRM по лидам и назначениям.
 */
export function SpendPage() {
  const [days, setDays] = useState(30);
  return (
    <PageBody>
      <PageHeader
        title={t.page.spend}
        extra={
          <Segmented<number>
            aria-label={t.spend.period}
            value={days}
            onChange={(v) => {
              setDays(v);
            }}
            options={PERIODS.map((n) => ({
              value: n,
              label: t.spend.periodDays.replace("{n}", String(n)),
            }))}
          />
        }
      />
      <UrlTabs
        label={t.aiSpend.tabs}
        items={[
          { key: "ensemble", label: t.aiSpend.tabEnsemble, children: <AiSpendPanel days={days} /> },
          { key: "crm", label: t.aiSpend.tabCrm, children: <CrmSpend days={days} /> },
        ]}
      />
    </PageBody>
  );
}
