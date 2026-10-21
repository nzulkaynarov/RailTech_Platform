import { Alert, Button, Card, Descriptions, Layout, Skeleton, Typography } from "antd";
import { useTranslation } from "react-i18next";

import { useGetHealth } from "../../shared/api/generated/platform-bff";
import type { Health } from "../../shared/api/generated/model";
import { StatusTag } from "../../shared/ui/StatusTag";

const SOURCES = ["redis", "crm", "erp"] as const;

function HealthDetails({ health }: { health: Health }) {
  const { t } = useTranslation();
  return (
    <Descriptions column={1} size="small" styles={{ label: { width: 180 } }}>
      <Descriptions.Item label={t("scaffold.health.overall")}>
        <span data-testid="health-status">
          <StatusTag kind={health.status === "ok" ? "success" : "warning"}>
            {t(`scaffold.health.status.${health.status}`)}
          </StatusTag>
        </span>
      </Descriptions.Item>
      {SOURCES.map((source) => (
        <Descriptions.Item key={source} label={t(`scaffold.health.sources.${source}`)}>
          <StatusTag kind={health.checks[source] === "ok" ? "success" : "error"}>
            {t(`scaffold.health.check.${health.checks[source]}`)}
          </StatusTag>
        </Descriptions.Item>
      ))}
      {health.version ? (
        <Descriptions.Item label={t("scaffold.health.version")}>{health.version}</Descriptions.Item>
      ) : null}
    </Descriptions>
  );
}

/** Страница-заглушка P0: доказывает цепочку web → BFF (getHealth через хук orval). Заменяется в P1. */
export function ScaffoldPage() {
  const { t } = useTranslation();
  const health = useGetHealth();

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Content style={{ padding: 24, maxWidth: 800 }}>
        <Typography.Title level={1} style={{ fontSize: 20, lineHeight: "28px", marginTop: 0 }}>
          {t("scaffold.title")}
        </Typography.Title>
        <Typography.Paragraph type="secondary">{t("scaffold.lead")}</Typography.Paragraph>
        <Card title={t("scaffold.health.title")}>
          {health.isPending ? (
            <div role="status" aria-label={t("scaffold.health.loading")}>
              <Skeleton active paragraph={{ rows: 3 }} title={false} />
            </div>
          ) : health.isError ? (
            <Alert
              type="error"
              showIcon
              message={t("scaffold.health.error")}
              action={
                <Button size="small" onClick={() => void health.refetch()}>
                  {t("scaffold.health.retry")}
                </Button>
              }
            />
          ) : (
            <HealthDetails health={health.data} />
          )}
        </Card>
      </Layout.Content>
    </Layout>
  );
}
