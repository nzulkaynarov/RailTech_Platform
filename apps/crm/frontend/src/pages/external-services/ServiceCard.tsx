import { ReloadOutlined } from "@ant-design/icons";
import { Button, Card, Descriptions, Flex, Typography } from "antd";
import { Link } from "react-router";

import type { ExternalServiceOut } from "../../api/generated/model";
import { metricRows, percent } from "../../domain/externalServices";
import { t } from "../../i18n/ru";
import { fromNow } from "../../lib/time";
import { ServiceProblem, ServiceStatusTag } from "./parts";

const MAX_METRICS = 4;

type Props = {
  service: ExternalServiceOut;
  now: Date;
  checking: boolean;
  onCheck: (service: ExternalServiceOut) => void;
  onSwitch: (service: ExternalServiceOut) => void;
};

/**
 * Карточка сервиса: статус, что сейчас, «что сделать» с кнопкой к настройке, главные метрики,
 * доступность за сутки, «Проверить сейчас» и выключатель (если он у сервиса есть).
 */
export function ServiceCard({ service, now, checking, onCheck, onSwitch }: Props) {
  const s = t.externalServices;
  const metrics = metricRows(service.metrics).slice(0, MAX_METRICS);
  const titleId = `service-${service.key.replace(/\W/g, "-")}`;
  const sw = service.switch;
  return (
    <Card size="small" className="service-card" aria-labelledby={titleId}>
      <Flex vertical gap="small">
        <Flex justify="space-between" align="start" gap="small" wrap>
          <Typography.Title level={3} className="service-title" id={titleId}>
            <Link to={`/external-services/${service.key}`}>{service.title}</Link>
          </Typography.Title>
          <ServiceStatusTag status={service.status} />
        </Flex>
        <Typography.Text type="secondary">{service.purpose}</Typography.Text>
        <Typography.Text>{service.summary}</Typography.Text>
        <ServiceProblem service={service} />
        {metrics.length ? (
          <Descriptions
            size="small"
            column={1}
            items={metrics.map((m) => ({ key: m.key, label: m.label, children: m.value }))}
          />
        ) : null}
        <Typography.Text type="secondary" className="service-meta">
          {service.checked_at
            ? s.lastCheck.replace("{when}", fromNow(service.checked_at, now))
            : s.lastCheck.replace("{when}", s.never)}
          {service.uptime_24h !== null ? ` · ${s.uptime24}: ${percent(service.uptime_24h)}` : ""}
        </Typography.Text>
        <Flex wrap gap="small">
          <Button
            size="small"
            icon={<ReloadOutlined aria-hidden />}
            loading={checking}
            onClick={() => {
              onCheck(service);
            }}
          >
            {s.checkNow}
          </Button>
          {sw && (sw.available || sw.disabled) ? (
            <Button
              size="small"
              danger={!sw.disabled}
              onClick={() => {
                onSwitch(service);
              }}
            >
              {sw.disabled ? s.switch.enable : s.switch.disable}
            </Button>
          ) : null}
        </Flex>
        {sw && !sw.available && !sw.disabled && sw.problem ? (
          <Typography.Text type="secondary" className="service-meta">
            {s.switch.unavailable}: {sw.problem}
          </Typography.Text>
        ) : null}
      </Flex>
    </Card>
  );
}
