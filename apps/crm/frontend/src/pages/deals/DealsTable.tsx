import { Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { DealOut } from "../../api/generated/model";
import { EntityLink } from "../../components/EntityLink";
import { ActionsTitle, RowActions } from "../../components/RowActions";
import { formatMoney, STAGE_COLORS, stageLabel } from "../../domain/deals";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";

type Props = {
  deals: DealOut[];
  loading?: boolean;
  /** Колонка «Клиент» не нужна на карточке клиента. */
  showClient?: boolean;
  onEdit: ((deal: DealOut) => void) | null;
};

function columns(showClient: boolean, onEdit: Props["onEdit"]): ColumnsType<DealOut> {
  const cols: ColumnsType<DealOut> = [
    { title: t.deals.title, dataIndex: "title", ellipsis: true },
    {
      title: t.deals.client,
      dataIndex: "client_name",
      render: (_: unknown, d) =>
        d.client_id ? (
          <EntityLink type="client" id={d.client_id}>
            {d.client_name ?? `#${String(d.client_id)}`}
          </EntityLink>
        ) : (
          t.common.none
        ),
    },
    {
      title: t.deals.amount,
      dataIndex: "amount",
      align: "right",
      render: (_: unknown, d) =>
        d.amount === null || d.amount === "" ? (
          <Tag bordered={false}>{t.deals.amountMissing}</Tag>
        ) : (
          formatMoney(d.amount, d.currency)
        ),
    },
    {
      title: t.deals.stage,
      dataIndex: "stage",
      render: (s: string) => <Tag color={STAGE_COLORS[s] ?? "default"}>{stageLabel(s)}</Tag>,
    },
    {
      title: t.deals.expected,
      dataIndex: "expected_close_date",
      responsive: ["md"],
      render: (v: string | null) => (v ? formatDate(v) : t.common.none),
    },
    {
      title: t.deals.owner,
      dataIndex: "owner_name",
      responsive: ["md"],
      render: (v: string | null) => v ?? t.common.none,
    },
    {
      title: t.deals.reason,
      dataIndex: "lost_reason",
      responsive: ["lg"],
      render: (v: string | null) => v ?? t.common.none,
    },
  ];
  if (!showClient) cols.splice(1, 1);
  if (onEdit) {
    cols.push({
      title: <ActionsTitle />,
      key: "actions",
      width: 56,
      render: (_: unknown, d) => (
        <RowActions
          label={t.deals.rowActions.replace("{title}", d.title)}
          actions={[
            {
              key: "edit",
              label: t.deals.edit,
              onClick: () => {
                onEdit(d);
              },
            },
          ]}
        />
      ),
    });
  }
  return cols;
}

/** Таблица сделок — общая для раздела «Сделки» и карточки клиента. */
export function DealsTable({ deals, loading, showClient = true, onEdit }: Props) {
  return (
    <Table<DealOut>
      rowKey="id"
      size="small"
      loading={loading ?? false}
      dataSource={deals}
      columns={columns(showClient, onEdit)}
      pagination={deals.length > 50 ? { pageSize: 50 } : false}
      scroll={{ x: "max-content" }}
    />
  );
}
