import { ReloadOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Card, Col, Flex, Row, Tag, Typography } from "antd";
import { useState } from "react";

import { useCheckService, useExternalServices } from "../../api/externalServiceQueries";
import type { ExternalServiceOut, ExternalServicesSummary } from "../../api/generated/model";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { groupServices, manuallyDisabled, summaryItems } from "../../domain/externalServices";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useNow } from "../../hooks/useNow";
import { t } from "../../i18n/ru";
import { DisabledBanner } from "./parts";
import { ServiceCard } from "./ServiceCard";
import { useSwitchFlow } from "./useSwitchFlow";

const SUMMARY_COLOR: Record<keyof ExternalServicesSummary, string> = {
  fail: "error",
  warn: "warning",
  ok: "success",
  unknown: "default",
  off: "default",
  disabled: "warning",
};

/** Сводка «Сбой N · Внимание N · В норме N …» — озвучивается как статус. */
function Summary({ summary }: { summary: ExternalServicesSummary }) {
  const s = t.externalServices.summary;
  return (
    <Flex wrap gap="small" role="status" aria-label={s["label"]}>
      {summaryItems(summary).map(({ key, count }) => (
        <Tag key={key} color={SUMMARY_COLOR[key]} className="summary-tag">
          {s[key]}: {count}
        </Tag>
      ))}
    </Flex>
  );
}

/**
 * «Внешние сервисы» (admin, M3-CRM-12): всё, что интегрировано помимо CRM и ERP, — статус, что
 * сделать при сбое, метрики, «Проверить сейчас» и выключатель. Страница моделей не вызывает.
 */
export function ExternalServicesPage() {
  const query = useExternalServices();
  const now = useNow();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const [checkingKey, setCheckingKey] = useState<string | null>(null);
  const check = useCheckService(onError, () => {
    void message.success(t.externalServices.checkedNow);
  });
  const { open, dialog } = useSwitchFlow();
  const s = t.externalServices;
  const services = query.data?.services ?? [];
  const onCheck = (service: ExternalServiceOut) => {
    setCheckingKey(service.key);
    check.mutate(
      { key: service.key },
      {
        onSettled: () => {
          setCheckingKey(null);
        },
      },
    );
  };
  return (
    <PageBody>
      <PageHeader
        title={t.page["external-services"]}
        extra={
          <Button
            icon={<ReloadOutlined aria-hidden />}
            loading={query.isFetching}
            onClick={() => {
              void query.refetch();
            }}
          >
            {s.refresh}
          </Button>
        }
      />
      <PageState query={query}>
        {query.data ? (
          <>
            <Card>
              <Flex vertical gap="small">
                <Typography.Paragraph type="secondary" className="service-intro">
                  {s.intro}
                </Typography.Paragraph>
                <Summary summary={query.data.summary} />
              </Flex>
            </Card>
            {manuallyDisabled(services).length ? (
              <DisabledBanner services={manuallyDisabled(services)} onEnable={open} />
            ) : null}
            {groupServices(services).map((group) => (
              <section key={group.key} aria-labelledby={`group-${group.key}`}>
                <Typography.Title level={2} className="section-title" id={`group-${group.key}`}>
                  {s.groups[group.key]}
                </Typography.Title>
                {s.groupHints[group.key] ? (
                  <Typography.Paragraph type="secondary">
                    {s.groupHints[group.key]}
                  </Typography.Paragraph>
                ) : null}
                <Row gutter={[16, 16]}>
                  {group.services.map((service) => (
                    <Col key={service.key} xs={24} lg={12} xxl={8}>
                      <ServiceCard
                        service={service}
                        now={now}
                        checking={checkingKey === service.key}
                        onCheck={onCheck}
                        onSwitch={open}
                      />
                    </Col>
                  ))}
                </Row>
              </section>
            ))}
          </>
        ) : null}
      </PageState>
      {dialog}
    </PageBody>
  );
}
