import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Segmented, Space, Typography } from "antd";
import { useState } from "react";

import { useDashboard } from "../../api/adminQueries";
import { refreshDashboard } from "../../api/generated/crm";
import { usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { dashboardTiles } from "../../domain/dashboard";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { formatDateTime, tashkent } from "../../lib/time";
import { Daily, Panels, Tiles } from "./DashboardParts";
import "../admin.css";

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
      await client.invalidateQueries({ queryKey: ["dashboard"] });
      void message.success(t.dashboard.refreshDone);
    },
    onError: useApiErrorToast(),
  });
}

function periodOf(days: number) {
  const now = tashkent(new Date());
  return { from: now.subtract(days - 1, "day").format("YYYY-MM-DD"), to: now.format("YYYY-MM-DD") };
}

/** Дашборд (SPEC §10.1): 4 ключевые метрики крупно, операционные — мельче; клик — к списку. */
export function DashboardPage() {
  const [days, setDays] = useState(30);
  const query = useDashboard(days);
  const perms = usePermissionsQuery();
  const refresh = useRefresh();
  const data = query.data;
  const tiles = data ? dashboardTiles(data, periodOf(days)) : null;
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
      <PageState query={query} ready={Boolean(data)}>
        {data && tiles ? (
          <>
            <Tiles tiles={tiles.primary} perms={perms.data} primary />
            <Typography.Title level={2} className="section-title">
              {t.dashboard.secondary}
            </Typography.Title>
            <Tiles tiles={tiles.secondary} perms={perms.data} primary={false} />
            <Panels funnel={data.funnel} reasons={data.escalation_reasons} />
            <Daily daily={data.daily} />
          </>
        ) : null}
      </PageState>
    </PageBody>
  );
}
