import { Grid, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { DealOut } from "../../api/generated/model";
import { EntityLink } from "../../components/EntityLink";
import { ActionsTitle, RowActions } from "../../components/RowActions";
import {
  externalStageColor,
  externalStageLabel,
  formatMoney,
  STAGE_COLORS,
  stageLabel,
} from "../../domain/deals";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";

type Props = {
  deals: DealOut[];
  loading?: boolean;
  /**
   * Вкладка «Сделки» карточки клиента: без колонки «Клиент», без липкой шапки и без
   * горизонтальной прокрутки — таблица укладывается в ширину, названия обрезаются. Иначе antd
   * делает тело таблицы прокручиваемой областью, а у наблюдателя в строках нет ни ссылок, ни
   * кнопок — её не прокрутить с клавиатуры (axe scrollable-region-focusable).
   */
  embedded?: boolean;
  onEdit: ((deal: DealOut) => void) | null;
};

/** Стадия сделки, стадия бэк-офиса и номер заявки ERP — метками. */
function StageTags({ deal: d }: { deal: DealOut }) {
  return (
    <Space size={4} wrap>
      <Tag color={STAGE_COLORS[d.stage] ?? "default"}>{stageLabel(d.stage)}</Tag>
      {d.external_stage ? (
        <Tag
          color={externalStageColor(d.external_stage)}
          bordered={false}
          title={t.deals.externalStageHint}
        >
          {externalStageLabel(d.external_stage)}
        </Tag>
      ) : null}
      {d.erp_deal_id ? (
        <Tag color="blue" bordered={false} title={t.deals.erpDeal}>
          #{String(d.erp_deal_id)}
        </Tag>
      ) : null}
    </Space>
  );
}

const titleCell = (compact: boolean): ColumnsType<DealOut>[number] =>
  compact
    ? {
        // Телефон: метки стадии — под названием, отдельной колонки «Стадия» нет (D-9).
        title: t.deals.title,
        dataIndex: "title",
        render: (title: string, d) => (
          <Space direction="vertical" size={4} style={{ width: "100%" }}>
            <Typography.Text>{title}</Typography.Text>
            <StageTags deal={d} />
          </Space>
        ),
      }
    : { title: t.deals.title, dataIndex: "title", ellipsis: true };

function columns(
  showClient: boolean,
  onEdit: Props["onEdit"],
  compact: boolean,
): ColumnsType<DealOut> {
  const cols: ColumnsType<DealOut> = [
    titleCell(compact),
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
      // Сумма не рвётся посреди числа на узком экране («28 000 00 / 0 UZS», D-9): колонка
      // не уже самой суммы, перенос внутри ячейки запрещён.
      width: 150,
      onCell: () => ({ style: { whiteSpace: "nowrap" } }),
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
      key: "stage",
      render: (_: unknown, d: DealOut) => <StageTags deal={d} />,
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
  if (compact)
    cols.splice(
      cols.findIndex((c) => c.key === "stage"),
      1,
    );
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
export function DealsTable({ deals, loading, embedded = false, onEdit }: Props) {
  // Карточка клиента на телефоне: узкая таблица, стадия уходит под название.
  const screens = Grid.useBreakpoint();
  const compact = embedded && screens.sm === false;
  return (
    <Table<DealOut>
      sticky={!embedded}
      rowKey="id"
      loading={loading ?? false}
      dataSource={deals}
      columns={columns(!embedded, onEdit, compact)}
      pagination={deals.length > 50 ? { pageSize: 50 } : false}
      {...(embedded ? {} : { scroll: { x: "max-content" } })}
    />
  );
}
