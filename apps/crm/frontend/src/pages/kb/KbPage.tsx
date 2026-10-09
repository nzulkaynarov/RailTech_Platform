import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Drawer, List, Space, Switch, Table, Typography } from "antd";
import { useState } from "react";

import { useKbChunks, useKbDocuments } from "../../api/adminQueries";
import {
  createManualDocument,
  reingestKbDocument,
  updateKbDocument,
  uploadKbDocument,
} from "../../api/generated/crm";
import type { KbDocumentOut } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { errorText, t } from "../../i18n/ru";
import { type ManualValues, ManualDialog, type UploadValues, UploadDialog } from "./KbDialogs";
import { TestSearch } from "./TestSearch";
import { IngestTag, LangTag } from "../../components/StageBadge";
import { formatDateTime } from "../../lib/time";

function useKbMutations(onDone: () => void) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const refresh = () => client.invalidateQueries({ queryKey: ["kb"] });
  const onError = (error: unknown) => {
    void message.error(errorText((error as ApiError).code, (error as Error).message));
  };
  const onSuccess = () => {
    onDone();
    void refresh();
    void message.success(t.common.saved);
  };
  return {
    upload: useMutation({
      mutationFn: async (v: UploadValues) => {
        const file = v.file[0]?.originFileObj;
        if (!file) throw new Error(t.kb.file);
        return unwrap(
          await uploadKbDocument({
            file,
            title: v.title,
            language: v.language,
            product_key: v.product_key ?? null,
          }),
        );
      },
      onSuccess,
      onError,
    }),
    manual: useMutation({
      mutationFn: async (v: ManualValues) =>
        unwrap(await createManualDocument({ ...v, product_key: v.product_key ?? null })),
      onSuccess,
      onError,
    }),
    toggle: useMutation({
      mutationFn: async (d: KbDocumentOut) =>
        unwrap(await updateKbDocument(d.id, { is_active: !d.is_active })),
      onSuccess: () => void refresh(),
      onError,
    }),
    reingest: useMutation({
      mutationFn: async (id: number) => unwrap(await reingestKbDocument(id)),
      onSuccess: () => void refresh(),
      onError,
    }),
  };
}

/** База знаний (admin, PLAN Фаза 5): документы, загрузка, индексация, фрагменты, тест поиска. */
export function KbPage() {
  const { data, isLoading } = useKbDocuments();
  const [dialog, setDialog] = useState<"upload" | "manual" | null>(null);
  const [chunksOf, setChunksOf] = useState<KbDocumentOut | null>(null);
  const chunks = useKbChunks(chunksOf?.id ?? null);
  const m = useKbMutations(() => {
    setDialog(null);
  });

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap>
        <Button
          type="primary"
          onClick={() => {
            setDialog("upload");
          }}
        >
          {t.kb.upload}
        </Button>
        <Button
          onClick={() => {
            setDialog("manual");
          }}
        >
          {t.kb.manual}
        </Button>
      </Space>
      <Table<KbDocumentOut>
        rowKey="id"
        loading={isLoading}
        dataSource={data ?? []}
        scroll={{ x: 800 }}
        pagination={{ pageSize: 20 }}
        columns={[
          {
            title: t.kb.title,
            render: (_, d) => (
              <a
                onClick={() => {
                  setChunksOf(d);
                }}
              >
                {d.title}
              </a>
            ),
          },
          {
            title: t.kb.language,
            dataIndex: "language",
            width: 70,
            render: (v: string) => <LangTag language={v} />,
          },
          {
            title: t.kb.product,
            dataIndex: "product_key",
            render: (v: string | null) => v ?? t.common.none,
          },
          {
            title: t.kb.status,
            render: (_, d) => (
              <Space direction="vertical" size={0}>
                <IngestTag status={d.ingest_status} />
                {d.ingest_error ? (
                  <Typography.Text type="danger" ellipsis style={{ maxWidth: 200 }}>
                    {d.ingest_error}
                  </Typography.Text>
                ) : null}
              </Space>
            ),
          },
          { title: t.kb.chunks, dataIndex: "chunk_count", width: 90 },
          {
            title: t.kb.active,
            render: (_, d) => (
              <Switch
                checked={d.is_active}
                onChange={() => {
                  m.toggle.mutate(d);
                }}
              />
            ),
          },
          {
            title: "",
            render: (_, d) => (
              <Button
                size="small"
                onClick={() => {
                  m.reingest.mutate(d.id);
                }}
              >
                {t.kb.reingest}
              </Button>
            ),
          },
          {
            title: t.kb.updated,
            dataIndex: "updated_at",
            render: (v: string) => formatDateTime(v),
          },
        ]}
      />
      <TestSearch />
      <UploadDialog
        open={dialog === "upload"}
        saving={m.upload.isPending}
        onCancel={() => {
          setDialog(null);
        }}
        onSubmit={(v) => {
          m.upload.mutate(v);
        }}
      />
      <ManualDialog
        open={dialog === "manual"}
        saving={m.manual.isPending}
        onCancel={() => {
          setDialog(null);
        }}
        onSubmit={(v) => {
          m.manual.mutate(v);
        }}
      />
      <Drawer
        open={chunksOf !== null}
        title={chunksOf?.title}
        width="min(640px, 100vw)"
        onClose={() => {
          setChunksOf(null);
        }}
      >
        <List
          loading={chunks.isLoading}
          dataSource={chunks.data ?? []}
          renderItem={(c) => (
            <List.Item>
              <Space direction="vertical" size={0}>
                <Typography.Text type="secondary">
                  #{c.position} · {c.heading_path ?? ""} · {c.token_count} {t.kb.tokens}
                </Typography.Text>
                <Typography.Paragraph style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                  {c.content}
                </Typography.Paragraph>
              </Space>
            </List.Item>
          )}
        />
      </Drawer>
    </Space>
  );
}
