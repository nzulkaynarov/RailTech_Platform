import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Col, Row, Segmented, Skeleton, Space, Typography } from "antd";
import { lazy, Suspense, useState } from "react";

import { useDashboard } from "../../api/adminQueries";
import { useDealsSummary } from "../../api/dealQueries";
import { getGetDashboardQueryKey, refreshDashboard } from "../../api/generated/crm";
import { usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { SetupChecklistCard } from "../../components/SetupChecklistCard";
import { PageState } from "../../components/PageState";
import { dashboardTiles } from "../../domain/dashboard";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { formatDateTime, tashkent } from "../../lib/time";
import { Daily, ManagersCard, Tiles } from "./DashboardParts";
import "../admin.css";

/** Графики — отдельным чанком: `@ant-design/plots` не попадает в другие страницы. */
const DashboardCharts = lazy(() => import("./DashboardCharts"));

const PERIODS = [7, 30, 90].map((n) => ({
  value: n,
  label: t.dashboard.days.replace("{n}", String(n)),
}));

function useRefresh() {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  return useMutation({
    mutationFn: refreshDashboard,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: getGetDashboardQueryKey() });
      void message.success(t.dashboard.refreshDone);
    },
    onError: useApiErrorToast(),
  });
}

function periodOf(days: number) {
  const now = tashkent(new Date());
  return { from: now.subtract(days - 1, "day").format("YYYY-MM-DD"), to: now.format("YYYY-MM-DD") };
}

/**
 * Дашборд (SPEC §10.1, UX волна 4): KPI с трендом к прошлому периоду, графики
 * (`@ant-design/plots`), менеджеры и SLA; таблица по дням — свёрнута. Клик по KPI — к списку.
 */
export function DashboardPage() {
  const [days, setDays] = useState(30);
  const query = useDashboard(days);
  const perms = usePermissionsQuery();
  const withDeals = allowed(perms.data, "deals", "read");
  const deals = useDealsSummary(days, withDeals);
  const refresh = useRefresh();
  const data = query.data;
  const dealsData = withDeals ? deals.data : undefined;
  const tiles = data ? dashboardTiles(data, periodOf(days), dealsData) : null;
  const controls = (
    <Space wrap>
      <Segmented
        aria-label={t.dashboard.period}
        value={days}
        options={PERIODS}
        onChange={setDays}
      />
      {data?.refreshed_at ? (
        <Typography.Text type="secondary">
          {t.dashboard.refreshed}: {formatDateTime(data.refreshed_at)}
        </Typography.Text>
      ) : null}
      {allowed(perms.data, "settings", "write") ? (
        <Button
          size="small"
          loading={refresh.isPending}
          onClick={() => {
            refresh.mutate();
          }}
        >
          {t.dashboard.refresh}
        </Button>
      ) : null}
    </Space>
  );
  return (
    <PageBody>
      <PageHeader title={t.page.dashboard} extra={controls} />
      <SetupChecklistCard />
      <PageState query={query} ready={Boolean(data)}>
        {data && tiles ? (
          <>
            <Tiles tiles={tiles.primary} perms={perms.data} primary />
            <Tiles tiles={tiles.secondary} perms={perms.data} primary={false} />
            <Suspense fallback={<Skeleton active aria-label={t.charts.loading} />}>
              <DashboardCharts data={data} deals={dealsData} />
            </Suspense>
            <Row gutter={[16, 16]}>
              <Col xs={24}>
                <ManagersCard managers={data.managers ?? []} sla={data.sla} />
              </Col>
            </Row>
            <Daily daily={data.daily} withCost={allowed(perms.data, "spend", "read")} />
          </>
        ) : null}
      </PageState>
    </PageBody>
  );
}
