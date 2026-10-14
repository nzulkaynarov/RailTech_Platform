import { Alert, Button, Flex, Tag, Typography } from "antd";
import { useNavigate } from "react-router";

import type { ExternalServiceOut } from "../../api/generated/model";
import type { ServiceStatus } from "../../domain/externalServices";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

/** Цвет тега — пресеты Ant Design (берут цвета из токенов темы). */
const TAG_COLOR: Record<ServiceStatus, string> = {
  ok: "success",
  warn: "warning",
  fail: "error",
  unknown: "default",
  off: "default",
};

export function ServiceStatusTag({ status }: { status: ServiceStatus }) {
  return <Tag color={TAG_COLOR[status]}>{t.externalServices.status[status] ?? status}</Tag>;
}

/**
 * «Что случилось — что сделать — кнопка туда, где это исправляется» (§3.13). Для исправного
 * сервиса ничего не показывает.
 */
export function ServiceProblem({ service }: { service: ExternalServiceOut }) {
  const s = t.externalServices;
  const navigate = useNavigate();
  const fixPath = service.fix_path;
  if (!service.hint && !service.error) return null;
  const type = service.status === "fail" ? "error" : service.status === "warn" ? "warning" : "info";
  return (
    <Alert
      type={type}
      showIcon
      message={service.hint ? `${s.whatToDo}: ${service.hint}` : service.summary}
      description={
        service.error ? (
          <Typography.Text type="secondary" className="service-error">
            {s.error}: {service.error}
          </Typography.Text>
        ) : undefined
      }
      action={
        fixPath ? (
          <Button
            size="small"
            onClick={() => {
              void navigate(fixPath);
            }}
          >
            {s.fix}
          </Button>
        ) : undefined
      }
    />
  );
}

/** Баннер «Выключено вручную» с причиной, кем и когда, и кнопкой «Включить». */
export function DisabledBanner({
  services,
  onEnable,
}: {
  services: ExternalServiceOut[];
  onEnable: (service: ExternalServiceOut) => void;
}) {
  const s = t.externalServices.switch;
  return (
    <Flex vertical gap="small">
      {services.map((service) => {
        const sw = service.switch;
        const who =
          sw?.changed_by && sw.changed_at
            ? s.disabledBy
                .replace("{who}", sw.changed_by)
                .replace("{when}", formatDateTime(sw.changed_at))
            : null;
        return (
          <Alert
            key={service.key}
            type="warning"
            showIcon
            role="status"
            message={s.disabledBanner.replace("{title}", service.title)}
            description={[sw?.reason, who].filter(Boolean).join(" · ") || undefined}
            action={
              <Button
                size="small"
                onClick={() => {
                  onEnable(service);
                }}
              >
                {s.enable}
              </Button>
            }
          />
        );
      })}
    </Flex>
  );
}
