import { Card, Segmented, Skeleton, Typography } from "antd";
import { lazy, Suspense, useState } from "react";

import { useSpend } from "../../api/spendQueries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { PROVIDER_CONSOLES } from "../../domain/spend";
import { t } from "../../i18n/ru";
import "../admin.css";

const PERIODS = [7, 30, 90];

/** Графики и таблицы — отдельным чанком (`@ant-design/plots` не попадает в другие страницы). */
const SpendCharts = lazy(() => import("./SpendCharts"));

/** «Расходы» (админ): сегодня против лимитов, по дням, по назначению, работа/тесты, лиды. */
export function SpendPage() {
  const [days, setDays] = useState(30);
  const query = useSpend(days);
  const report = query.data;
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
    </PageBody>
  );
}
