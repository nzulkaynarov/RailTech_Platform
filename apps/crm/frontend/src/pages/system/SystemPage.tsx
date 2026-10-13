import { ReloadOutlined } from "@ant-design/icons";
import { Button, Card, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Link } from "react-router";

import { useSystemStatus } from "../../api/adminQueries";
import type { ComponentStatusOut } from "../../api/generated/model";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { bySeverity, componentPath, headerHealth } from "../../domain/systemHealth";
import { useNow } from "../../hooks/useNow";
import { t } from "../../i18n/ru";
import { fromNow } from "../../lib/time";

/** Цвет тега — пресеты Ant Design, они берут цвета из токенов темы (colorSuccess и т. д.). */
const TAG_COLOR: Record<ComponentStatusOut["status"], string> = {
  ok: "success",
  warn: "warning",
  fail: "error",
  unknown: "default",
};

export function StatusTag({ status }: { status: ComponentStatusOut["status"] }) {
  return <Tag color={TAG_COLOR[status]}>{t.system.status[status] ?? status}</Tag>;
}

/** В колонке «Проверено» — только «N назад»: слово «проверено» уже в заголовке. */
function checkedText(at: string | null | undefined, now: Date): string {
  return at ? fromNow(at, now) : t.system.neverChecked;
}

/**
 * Одна строка на компонент: статус · компонент (ссылка туда, где чинится) · причина (обрезка,
 * целиком — в подсказке) · когда проверено.
 */
function columns(now: Date): ColumnsType<ComponentStatusOut> {
  const c = t.system.columns;
  return [
    {
      title: c.status,
      dataIndex: "status",
      width: 120,
      render: (status: ComponentStatusOut["status"]) => <StatusTag status={status} />,
    },
    {
      title: c.component,
      dataIndex: "title",
      width: 220,
      ellipsis: true,
      render: (title: string, row) => {
        const path = componentPath(row.key);
        return path ? <Link to={path}>{title}</Link> : title;
      },
    },
    {
      title: c.reason,
      dataIndex: "reason",
      ellipsis: { showTitle: false },
      render: (reason: string | null | undefined) =>
        reason ? <Tooltip title={reason}>{reason}</Tooltip> : t.common.none,
    },
    {
      title: c.checked,
      dataIndex: "checked_at",
      className: "nowrap",
      width: 200,
      render: (at: string | null | undefined) => (
        <Typography.Text type="secondary">{checkedText(at, now)}</Typography.Text>
      ),
    },
  ];
}

/** «Состояние системы» (admin): бот, канал, модели, очередь, бэкап, секреты — с причиной сбоя. */
export function SystemPage() {
  const query = useSystemStatus();
  const now = useNow();
  return (
    <PageBody>
      <PageHeader
        title={t.page.system}
        extra={
          <Button
            icon={<ReloadOutlined aria-hidden />}
            loading={query.isFetching}
            onClick={() => {
              void query.refetch();
            }}
          >
            {t.system.refresh}
          </Button>
        }
      />
      <PageState query={query}>
        {query.data ? (
          <Card>
            <Typography.Paragraph strong>
              {headerHealth(query.data).tone === "ok"
                ? t.system.allOk
                : headerHealth(query.data).label}
            </Typography.Paragraph>
            <Typography.Paragraph type="secondary">{t.system.hint}</Typography.Paragraph>
            <Table<ComponentStatusOut>
              rowKey="key"
              pagination={false}
              scroll={{ x: 640 }}
              dataSource={bySeverity(query.data.components)}
              columns={columns(now)}
            />
          </Card>
        ) : null}
      </PageState>
    </PageBody>
  );
}
