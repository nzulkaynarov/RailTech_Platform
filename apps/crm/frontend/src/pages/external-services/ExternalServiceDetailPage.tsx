import { ReloadOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Card, Descriptions, Flex, Typography } from "antd";
import { useParams } from "react-router";

import { useCheckService, useExternalService } from "../../api/externalServiceQueries";
import type { ExternalServiceOut } from "../../api/generated/model";
import { useEntityDocumentTitle } from "../../app/documentTitle";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState, QueryError } from "../../components/PageState";
import { metricRows, percent } from "../../domain/externalServices";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useNow } from "../../hooks/useNow";
import { t } from "../../i18n/ru";
import { formatNumber } from "../../lib/format";
import { formatDateTime, fromNow } from "../../lib/time";
import { DaysTable, HistoryTable, IncidentsTable } from "./DetailTables";
import { DisabledBanner, ServiceProblem, ServiceStatusTag } from "./parts";
import { useSwitchFlow } from "./useSwitchFlow";

function StateCard({ service, now }: { service: ExternalServiceOut; now: Date }) {
  const s = t.externalServices;
  return (
    <Card title={s.stateTitle}>
      <Flex vertical gap="small">
        <Flex gap="small" align="center" wrap>
          <ServiceStatusTag status={service.status} />
          <Typography.Text>{service.summary}</Typography.Text>
        </Flex>
        <ServiceProblem service={service} />
        {service.incident ? (
          <Typography.Text type="danger">
            {s.incident.open.replace("{when}", formatDateTime(service.incident.started_at))}
          </Typography.Text>
        ) : null}
        <Descriptions
          size="small"
          column={1}
          items={[
            { key: "purpose", label: s.purpose, children: service.purpose },
            { key: "system", label: s.usedBy, children: s.system[service.system] },
            { key: "check", label: s.howChecked, children: service.check },
            { key: "freq", label: s.howOften, children: s.frequency[service.frequency] },
            {
              key: "checked",
              label: s.checked,
              children: service.checked_at ? fromNow(service.checked_at, now) : s.never,
            },
          ]}
        />
      </Flex>
    </Card>
  );
}

function MetricsCard({ service }: { service: ExternalServiceOut }) {
  const s = t.externalServices;
  const items = [
    { key: "uptime24", label: s.uptime24, children: percent(service.uptime_24h) },
    { key: "uptime7", label: s.uptime7d, children: percent(service.uptime_7d) },
    { key: "checks", label: s.checks24, children: formatNumber(service.checks_24h) },
    { key: "fails", label: s.failures24, children: formatNumber(service.failures_24h) },
    {
      key: "p95",
      label: s.p95,
      children:
        service.p95_ms_24h === null ? t.common.none : `${formatNumber(service.p95_ms_24h)} мс`,
    },
    ...metricRows(service.metrics).map((m) => ({ key: m.key, label: m.label, children: m.value })),
  ];
  return (
    <Card title={s.detailsTitle}>
      <Descriptions size="small" column={{ xs: 1, md: 2 }} items={items} />
    </Card>
  );
}

/** Деталка сервиса: состояние, «что сделать», показатели, 7 дней, проверки за сутки, инциденты. */
export function ExternalServiceDetailPage() {
  const { key = "" } = useParams();
  const query = useExternalService(key);
  const now = useNow();
  const { message } = AntApp.useApp();
  const check = useCheckService(useApiErrorToast(), () => {
    void message.success(t.externalServices.checkedNow);
  });
  const { open, dialog } = useSwitchFlow();
  const service = query.data?.service;
  useEntityDocumentTitle(service?.title);
  const s = t.externalServices;
  const sw = service?.switch;
  return (
    <PageBody>
      <PageHeader
        title={service?.title ?? t.page["external-services"]}
        back="/external-services"
        extra={
          service ? (
            <Flex wrap gap="small">
              {service.source === "crm" ? (
                <Button
                  icon={<ReloadOutlined aria-hidden />}
                  loading={check.isPending}
                  onClick={() => {
                    check.mutate({ key });
                  }}
                >
                  {s.checkNow}
                </Button>
              ) : null}
              {sw && (sw.available || sw.disabled) ? (
                <Button
                  danger={!sw.disabled}
                  onClick={() => {
                    open(service);
                  }}
                >
                  {sw.disabled ? s.switch.enable : s.switch.disable}
                </Button>
              ) : null}
            </Flex>
          ) : null
        }
      />
      {query.isError ? (
        <QueryError
          error={query.error}
          notFound={s.notFound}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : (
        <PageState query={query}>
          {query.data && service ? (
            <>
              {sw?.disabled ? <DisabledBanner services={[service]} onEnable={open} /> : null}
              <StateCard service={service} now={now} />
              <MetricsCard service={service} />
              <DaysTable days={query.data.days} />
              <HistoryTable checks={query.data.checks} />
              <IncidentsTable incidents={query.data.incidents} />
            </>
          ) : null}
        </PageState>
      )}
      {dialog}
    </PageBody>
  );
}
