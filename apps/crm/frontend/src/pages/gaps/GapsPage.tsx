import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Modal, Segmented, Select, Space, Table } from "antd";
import { useState } from "react";
import { Link } from "react-router";

import { useKbDocuments, useKbGaps } from "../../api/adminQueries";
import { createManualDocument, ignoreGap, reopenGap, resolveGap } from "../../api/generated/crm";
import type { KbGapOut, ListKbGapsStatus } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { errorText, t } from "../../i18n/ru";
import { type ManualValues, ManualDialog } from "../kb/KbDialogs";

type Action =
  | { kind: "ignore" | "reopen"; gap: KbGapOut }
  | { kind: "link"; gap: KbGapOut; documentId: number };

/** Пробелы KB (сценарий C4): вопросы без ответа → документ, привязка или игнор. */
export function GapsPage() {
  const [status, setStatus] = useState<ListKbGapsStatus>("open");
  const { data, isLoading } = useKbGaps({ status, limit: 200 });
  const docs = useKbDocuments();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const [creating, setCreating] = useState<KbGapOut | null>(null);
  const [linking, setLinking] = useState<KbGapOut | null>(null);
  const [documentId, setDocumentId] = useState<number | null>(null);

  const done = () => {
    void client.invalidateQueries({ queryKey: ["kb"] });
    void message.success(t.common.saved);
  };
  const onError = (e: unknown) => {
    void message.error(errorText((e as ApiError).code, (e as Error).message));
  };
  const act = useMutation({
    mutationFn: async (a: Action) => {
      if (a.kind === "link")
        return unwrap(await resolveGap(a.gap.id, { document_id: a.documentId }));
      if (a.kind === "ignore") return unwrap(await ignoreGap(a.gap.id));
      return unwrap(await reopenGap(a.gap.id));
    },
    onSuccess: () => {
      setLinking(null);
      done();
    },
    onError,
  });
  const create = useMutation({
    mutationFn: async (v: ManualValues & { gapId: number }) =>
      unwrap(
        await createManualDocument({
          title: v.title,
          markdown: v.markdown,
          language: v.language,
          product_key: v.product_key ?? null,
          gap_id: v.gapId,
        }),
      ),
    onSuccess: () => {
      setCreating(null);
      done();
    },
    onError,
  });

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Segmented
        value={status}
        onChange={(v) => {
          setStatus(v);
        }}
        options={(["open", "resolved", "ignored"] as const).map((v) => ({
          value: v,
          label: t.gaps.statuses[v],
        }))}
      />
      <Table<KbGapOut>
        rowKey="id"
        loading={isLoading}
        dataSource={data?.items ?? []}
        scroll={{ x: 760 }}
        pagination={{ pageSize: 50 }}
        columns={[
          { title: t.gaps.question, dataIndex: "question" },
          {
            title: t.gaps.occurrences,
            dataIndex: "occurrences",
            width: 70,
            sorter: (a, b) => a.occurrences - b.occurrences,
          },
          { title: t.gaps.language, dataIndex: "language", width: 70 },
          {
            title: t.gaps.score,
            render: (_, g) => g.best_score?.toFixed(2) ?? t.common.none,
            width: 110,
          },
          {
            title: t.gaps.lead,
            render: (_, g) =>
              g.lead_id ? (
                <Link to={`/leads/${String(g.lead_id)}`}>#{g.lead_id}</Link>
              ) : (
                t.common.none
              ),
            width: 70,
          },
          {
            title: "",
            render: (_, g) =>
              g.status === "open" ? (
                <Space wrap>
                  <Button
                    size="small"
                    type="primary"
                    onClick={() => {
                      setCreating(g);
                    }}
                  >
                    {t.gaps.create}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      setLinking(g);
                      setDocumentId(null);
                    }}
                  >
                    {t.gaps.link}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      act.mutate({ kind: "ignore", gap: g });
                    }}
                  >
                    {t.gaps.ignore}
                  </Button>
                </Space>
              ) : (
                <Button
                  size="small"
                  onClick={() => {
                    act.mutate({ kind: "reopen", gap: g });
                  }}
                >
                  {t.gaps.reopen}
                </Button>
              ),
          },
        ]}
      />
      <ManualDialog
        open={creating !== null}
        saving={create.isPending}
        initial={
          creating
            ? {
                title: creating.question.slice(0, 200),
                language: creating.language as ManualValues["language"],
                markdown: `## ${creating.question}\n\n`,
              }
            : {}
        }
        onCancel={() => {
          setCreating(null);
        }}
        onSubmit={(v) => {
          if (creating) create.mutate({ ...v, gapId: creating.id });
        }}
      />
      <Modal
        open={linking !== null}
        title={t.gaps.link}
        confirmLoading={act.isPending}
        okButtonProps={{ disabled: documentId === null }}
        onCancel={() => {
          setLinking(null);
        }}
        onOk={() => {
          if (linking && documentId !== null)
            act.mutate({ kind: "link", gap: linking, documentId });
        }}
      >
        <Select
          showSearch
          style={{ width: "100%" }}
          placeholder={t.gaps.document}
          optionFilterProp="label"
          value={documentId}
          onChange={(v: number) => {
            setDocumentId(v);
          }}
          options={(docs.data ?? [])
            .filter((d) => d.is_active)
            .map((d) => ({ value: d.id, label: d.title }))}
        />
      </Modal>
    </Space>
  );
}
