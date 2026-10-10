import { Button, Table } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { KbGapOut } from "../../api/generated/model";
import { LeadLink } from "../../components/EntityLink";
import { ActionsTitle, type RowAction, RowActions } from "../../components/RowActions";
import { LangTag } from "../../components/StageBadge";
import { t } from "../../i18n/ru";

type Handlers = {
  onCreate: (gap: KbGapOut) => void;
  onLink: (gap: KbGapOut) => void;
  onIgnore: (gap: KbGapOut) => void;
  onReopen: (gap: KbGapOut) => void;
};

function rowActions(g: KbGapOut, h: Handlers): RowAction[] {
  if (g.status !== "open") {
    return [
      {
        key: "reopen",
        label: t.gaps.reopen,
        onClick: () => {
          h.onReopen(g);
        },
      },
    ];
  }
  return [
    {
      key: "link",
      label: t.gaps.link,
      onClick: () => {
        h.onLink(g);
      },
    },
    {
      key: "ignore",
      label: t.gaps.ignore,
      danger: true,
      onClick: () => {
        h.onIgnore(g);
      },
    },
  ];
}

function columns(h: Handlers): ColumnsType<KbGapOut> {
  return [
    { title: t.gaps.question, dataIndex: "question" },
    {
      title: t.gaps.occurrences,
      dataIndex: "occurrences",
      width: 110,
      sorter: (a, b) => a.occurrences - b.occurrences,
    },
    {
      title: t.gaps.language,
      dataIndex: "language",
      width: 72,
      render: (v: string) => <LangTag language={v} />,
    },
    {
      title: t.gaps.score,
      width: 100,
      render: (_, g) => g.best_score?.toFixed(2) ?? t.common.none,
    },
    {
      title: t.gaps.lead,
      width: 90,
      render: (_, g) => (g.lead_id ? <LeadLink id={g.lead_id} /> : t.common.none),
    },
    {
      title: <ActionsTitle />,
      width: 210,
      render: (_, g) => (
        <span className="row-actions">
          {g.status === "open" ? (
            <Button
              size="small"
              onClick={() => {
                h.onCreate(g);
              }}
            >
              {t.gaps.create}
            </Button>
          ) : null}
          <RowActions label={t.gaps.rowActions} actions={rowActions(g, h)} />
        </span>
      ),
    },
  ];
}

/** Пробелы: частое действие («Создать документ») — в строке, остальное — в «⋯». */
export function GapsTable({
  data,
  loading,
  ...h
}: Handlers & { data: KbGapOut[]; loading: boolean }) {
  return (
    <Table<KbGapOut>
      rowKey="id"
      loading={loading}
      dataSource={data}
      scroll={{ x: 760 }}
      pagination={{ pageSize: 50, hideOnSinglePage: true }}
      columns={columns(h)}
    />
  );
}
