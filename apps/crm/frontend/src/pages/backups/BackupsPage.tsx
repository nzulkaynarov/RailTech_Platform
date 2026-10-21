import { Alert, App as AntApp, Button, Card, Descriptions, Flex, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { BackupDatabase, BackupItem } from "../../api/generated/model";
import { useBackups, useRequestBackup } from "../../api/systemQueries";
import { EmptyState } from "../../components/EmptyState";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { formatBytes } from "../../domain/backups";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { formatDateTime, fromNow } from "../../lib/time";
import "../admin.css";

const columns: ColumnsType<BackupItem> = [
  { title: t.backups.name, dataIndex: "name", key: "name" },
  { title: t.backups.at, dataIndex: "at", key: "at", render: (v: string) => formatDateTime(v) },
  {
    title: t.backups.size,
    dataIndex: "size_bytes",
    key: "size",
    align: "right",
    render: (v: number) => formatBytes(v),
  },
];

const databaseColumns: ColumnsType<BackupDatabase> = [
  { title: t.backups.database, dataIndex: "name", key: "name" },
  {
    title: t.backups.last,
    dataIndex: "last_success_at",
    key: "at",
    render: (v: string | null) => (v ? `${formatDateTime(v)} (${fromNow(v)})` : t.backups.never),
  },
];

function staleText(source: "volume" | "rustfs", hasCopy: boolean): string {
  if (source === "rustfs") return hasCopy ? t.backups.staleBucket : t.backups.noneBucket;
  return hasCopy ? t.backups.stale : t.backups.none;
}

/**
 * Резервные копии (admin, ADR-0013): возраст последней копии, список и «Сделать сейчас».
 * Сервис бэкапа жив — по heartbeat; запрос, который он не забрал за 2 мин, можно повторить.
 * Восстановление выполняет администратор сервера (runbook backup-restore).
 * На проде (M5-CRM-01) копию делает VPS 2, CRM читает бакет «backups» RustFS: источник и время
 * копии по каждой базе показаны здесь же, «Сделать сейчас» нет (`can_request`), ошибка бакета —
 * с подсказкой «что сделать».
 */
export function BackupsPage() {
  const query = useBackups();
  const { message } = AntApp.useApp();
  const confirm = useConfirmDanger();
  const request = useRequestBackup(useApiErrorToast(), () => {
    void message.success(t.backups.started);
  });
  const data = query.data;
  const action =
    data?.available && data.can_request ? (
      <Button
        type="primary"
        loading={request.isPending}
        disabled={Boolean(data.requested_at)}
        onClick={() => {
          confirm({
            title: t.backups.confirm,
            content: t.backups.confirmHint,
            okText: t.backups.now,
            onOk: () => request.mutateAsync(),
          });
        }}
      >
        {t.backups.now}
      </Button>
    ) : null;
  return (
    <PageBody>
      <PageHeader title={t.page.backups} extra={action} />
      <PageState query={query} ready={Boolean(data)}>
        {data ? (
          <Flex vertical gap="middle">
            {data.error ? (
              <Alert
                type={data.error === "unreachable" ? "warning" : "error"}
                showIcon
                message={t.backups.errors[data.error] ?? t.backups.errors["unreachable"]}
              />
            ) : null}
            {!data.available && !data.error ? (
              <Alert type="info" showIcon message={t.backups.unavailable} />
            ) : null}
            {data.available && !data.daemon_alive ? (
              <Alert type="error" showIcon message={t.backups.daemonDown} />
            ) : null}
            {data.available && data.daemon_alive && data.request_stuck ? (
              <Alert type="warning" showIcon message={t.backups.stuck} />
            ) : null}
            {data.available && data.stale ? (
              <Alert
                type="warning"
                showIcon
                message={staleText(data.source, data.last_success_at !== null)}
              />
            ) : null}
            {data.requested_at ? (
              <Alert
                type="info"
                showIcon
                message={t.backups.requested.replace("{time}", formatDateTime(data.requested_at))}
              />
            ) : null}
            <Card size="small">
              <Descriptions
                size="small"
                column={1}
                items={[
                  {
                    key: "last",
                    label: t.backups.last,
                    children: data.last_success_at
                      ? `${formatDateTime(data.last_success_at)} (${fromNow(data.last_success_at)})`
                      : t.backups.never,
                  },
                  {
                    key: "source",
                    label: t.backups.sourceLabel,
                    children: t.backups.source[data.source],
                  },
                ]}
              />
              {data.source === "rustfs" ? (
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  {t.backups.sourceHint}
                </Typography.Paragraph>
              ) : null}
            </Card>
            {data.databases.length ? (
              <Flex vertical gap="small">
                <Typography.Title level={2} style={{ fontSize: 16, margin: 0 }}>
                  {t.backups.databases}
                </Typography.Title>
                <Table<BackupDatabase>
                  rowKey="name"
                  size="small"
                  columns={databaseColumns}
                  dataSource={data.databases}
                  pagination={false}
                />
              </Flex>
            ) : null}
            <Table<BackupItem>
              rowKey="name"
              columns={columns}
              dataSource={data.items}
              pagination={false}
              locale={{ emptyText: <EmptyState title={t.backups.empty} /> }}
            />
            <Typography.Paragraph type="secondary">{t.backups.restoreHint}</Typography.Paragraph>
          </Flex>
        ) : null}
      </PageState>
    </PageBody>
  );
}
