import { Button, Space, Switch, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { KbDocumentOut } from "../../api/generated/model";
import { ActionsTitle, RowActions } from "../../components/RowActions";
import { IngestTag, LangTag } from "../../components/StageBadge";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

type Handlers = {
  productName: (key: string | null) => string;
  onOpen: (d: KbDocumentOut) => void;
  onToggle: (d: KbDocumentOut) => void;
  onReingest: (d: KbDocumentOut) => void;
};

const named = (text: string, d: KbDocumentOut) => text.replace("{title}", d.title);

function infoColumns({ productName, onOpen }: Handlers): ColumnsType<KbDocumentOut> {
  return [
    {
      title: t.kb.title,
      render: (_, d) => (
        <Button
          type="link"
          className="link-button"
          onClick={() => {
            onOpen(d);
          }}
        >
          {d.title}
        </Button>
      ),
    },
    {
      title: t.kb.language,
      dataIndex: "language",
      width: 72,
      render: (v: string) => <LangTag language={v} />,
    },
    { title: t.kb.product, dataIndex: "product_key", render: (v: string | null) => productName(v) },
    {
      title: t.kb.status,
      render: (_, d) => (
        <Space direction="vertical" size={0}>
          <IngestTag status={d.ingest_status} />
          {d.ingest_error ? (
            <Typography.Text
              type="danger"
              ellipsis={{ tooltip: d.ingest_error }}
              className="cell-error"
            >
              {d.ingest_error}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    { title: t.kb.chunks, dataIndex: "chunk_count", width: 100 },
  ];
}

function controlColumns({ onOpen, onToggle, onReingest }: Handlers): ColumnsType<KbDocumentOut> {
  return [
    {
      title: t.kb.active,
      width: 90,
      render: (_, d) => (
        <Switch
          aria-label={named(t.kb.activeFor, d)}
          checked={d.is_active}
          onChange={() => {
            onToggle(d);
          }}
        />
      ),
    },
    {
      title: t.kb.updated,
      dataIndex: "updated_at",
      className: "nowrap",
      render: (v: string) => formatDateTime(v),
    },
    {
      title: <ActionsTitle />,
      className: "col-actions",
      render: (_, d) => (
        <RowActions
          label={named(t.kb.rowActions, d)}
          actions={[
            {
              key: "chunks",
              label: t.kb.showChunks,
              onClick: () => {
                onOpen(d);
              },
            },
            {
              key: "reingest",
              label: t.kb.reingest,
              onClick: () => {
                onReingest(d);
              },
            },
          ]}
        />
      ),
    },
  ];
}

/** Документы базы знаний: частое действие (вкл/выкл) — в строке, редкие — в «⋯». */
export function KbTable({
  data,
  loading,
  ...handlers
}: Handlers & { data: KbDocumentOut[]; loading: boolean }) {
  return (
    <Table<KbDocumentOut>
      rowKey="id"
      loading={loading}
      dataSource={data}
      scroll={{ x: 860 }}
      pagination={{ pageSize: 20, hideOnSinglePage: true }}
      columns={[...infoColumns(handlers), ...controlColumns(handlers)]}
    />
  );
}
