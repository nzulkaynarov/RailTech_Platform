import { ReloadOutlined } from "@ant-design/icons";
import { Button, Flex, Grid, List, Select, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import type { EmailLogItem, ListEmailLogStatus } from "../../api/generated/model";
import { useEmailLog } from "../../api/integrationQueries";
import { PageState } from "../../components/PageState";
import { EMAIL_STATUS_COLOR } from "../../domain/integrations";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";
import "../admin.css";

const S = t.integrations.smtp;
const STATUS_OPTIONS = Object.entries(t.emailStatus).map(([value, label]) => ({ value, label }));

function StatusTag({ row }: { row: EmailLogItem }) {
  const attempts = row.attempts > 1 ? ` (${S.attempts.replace("{n}", String(row.attempts))})` : "";
  return (
    <Tag color={EMAIL_STATUS_COLOR[row.status] ?? "default"}>
      {t.emailStatus[row.status] ?? row.status}
      {attempts}
    </Tag>
  );
}

const templateLabel = (code: string) => S.templates[code] ?? code;

function columns(): ColumnsType<EmailLogItem> {
  return [
    {
      title: S.logColumns.when,
      width: 150,
      render: (_, row) => formatDateTime(row.sent_at ?? row.created_at),
    },
    { title: S.logColumns.to, dataIndex: "to_email" },
    { title: S.logColumns.subject, dataIndex: "subject" },
    { title: S.logColumns.template, render: (_, row) => templateLabel(row.template) },
    { title: S.logColumns.status, render: (_, row) => <StatusTag row={row} /> },
    {
      title: S.logColumns.error,
      render: (_, row) =>
        row.error ? <Typography.Text type="secondary">{row.error}</Typography.Text> : null,
    },
  ];
}

/** На телефоне — карточки вместо таблицы (crm-page §8). */
function MailCards({ rows }: { rows: EmailLogItem[] }) {
  return (
    <List
      dataSource={rows}
      renderItem={(row) => (
        <List.Item>
          <Flex vertical gap={4} className="full-width">
            <Flex justify="space-between" gap="small" wrap>
              <Typography.Text strong>{row.to_email}</Typography.Text>
              <StatusTag row={row} />
            </Flex>
            <Typography.Text>{row.subject}</Typography.Text>
            <Typography.Text type="secondary">
              {templateLabel(row.template)} · {formatDateTime(row.sent_at ?? row.created_at)}
            </Typography.Text>
            {row.error ? <Typography.Text type="secondary">{row.error}</Typography.Text> : null}
          </Flex>
        </List.Item>
      )}
    />
  );
}

/** Журнал писем сотрудникам (M3-CRM-08): последние 50, фильтр по статусу; тел писем нет. */
export function MailLog() {
  const [status, setStatus] = useState<ListEmailLogStatus | undefined>(undefined);
  const query = useEmailLog(status ? { status, limit: 50 } : { limit: 50 });
  const phone = Grid.useBreakpoint().sm === false;
  const rows = query.data ?? [];
  return (
    <Flex vertical gap="small">
      <Flex justify="space-between" align="center" wrap gap="small">
        <Typography.Title level={2} className="section-title">
          {S.log}
        </Typography.Title>
        <Flex gap="small" wrap>
          <Select
            allowClear
            aria-label={S.logStatus}
            placeholder={S.logAll}
            className="filter-md"
            options={STATUS_OPTIONS}
            value={status}
            onChange={(value?: ListEmailLogStatus) => {
              setStatus(value);
            }}
          />
          <Button
            icon={<ReloadOutlined aria-hidden />}
            loading={query.isFetching}
            onClick={() => {
              void query.refetch();
            }}
          >
            {S.logRefresh}
          </Button>
        </Flex>
      </Flex>
      <Typography.Text type="secondary">{S.logHint}</Typography.Text>
      <PageState
        query={query}
        variant="section"
        empty={!rows.length && { title: S.logEmpty, hint: S.logEmptyHint, compact: true }}
      >
        {phone ? (
          <MailCards rows={rows} />
        ) : (
          <Table<EmailLogItem>
            size="small"
            rowKey="id"
            dataSource={rows}
            columns={columns()}
            pagination={false}
            scroll={{ x: 720 }}
          />
        )}
      </PageState>
    </Flex>
  );
}
