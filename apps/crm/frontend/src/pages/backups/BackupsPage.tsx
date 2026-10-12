import { Alert, App as AntApp, Button, Card, Flex, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { BackupItem } from "../../api/generated/model";
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

/**
 * Резервные копии (admin, ADR-0013): возраст последней копии, список и «Сделать сейчас».
 * Восстановление — только с сервера (runbook backup-restore).
 */
export function BackupsPage() {
  const query = useBackups();
  const { message } = AntApp.useApp();
  const confirm = useConfirmDanger();
  const request = useRequestBackup(useApiErrorToast(), () => {
    void message.success(t.backups.started);
  });
  const data = query.data;
  const action = data?.available ? (
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
            {!data.available ? (
              <Alert type="info" showIcon message={t.backups.unavailable} />
            ) : null}
            {data.available && data.stale ? (
              <Alert
                type="warning"
                showIcon
                message={data.last_success_at ? t.backups.stale : t.backups.none}
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
              <Typography.Text strong>{t.backups.last}: </Typography.Text>
              <Typography.Text>
                {data.last_success_at
                  ? `${formatDateTime(data.last_success_at)} (${fromNow(data.last_success_at)})`
                  : t.backups.never}
              </Typography.Text>
            </Card>
            <Table<BackupItem>
              rowKey="name"
              columns={columns}
              dataSource={data.items}
              pagination={false}
              scroll={{ x: "max-content" }}
              locale={{ emptyText: <EmptyState title={t.backups.empty} /> }}
            />
            <Typography.Paragraph type="secondary">{t.backups.restoreHint}</Typography.Paragraph>
          </Flex>
        ) : null}
      </PageState>
    </PageBody>
  );
}
