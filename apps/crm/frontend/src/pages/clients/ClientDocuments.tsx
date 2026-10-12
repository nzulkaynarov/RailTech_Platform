import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Flex, Switch, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import { adminKeys, useClientDocuments } from "../../api/adminQueries";
import { updateDocument, uploadDocument } from "../../api/generated/crm";
import type { DocumentOut } from "../../api/generated/model";
import { downloadFile, unwrap } from "../../api/http";
import { PageState } from "../../components/PageState";
import { ActionsTitle, RowActions } from "../../components/RowActions";
import { IngestTag } from "../../components/StageBadge";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";
import { AccessDrawer, UploadDocumentDialog, type UploadValues } from "./DocumentDialogs";

const named = (text: string, d: { title: string }) => text.replace("{title}", d.title);

function useDocumentMutations(clientId: number, onUploaded: () => void) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const refresh = () => client.invalidateQueries({ queryKey: adminKeys.clientDocuments(clientId) });
  const upload = useMutation({
    mutationFn: async (v: UploadValues) => {
      const file = v.file[0]?.originFileObj;
      if (!file) throw new Error(t.kb.file);
      const date = v.doc_date ? v.doc_date.format("YYYY-MM-DD") : null;
      const meta = { client_id: clientId, type: v.type, title: v.title, visible: v.visible };
      return unwrap(
        await uploadDocument({ file, ...meta, number: v.number ?? null, doc_date: date }),
      );
    },
    onSuccess: (_, v) => {
      onUploaded();
      void message.success(named(t.clients.uploaded, v));
      void refresh();
    },
    onError,
  });
  const toggle = useMutation({
    mutationFn: async (d: DocumentOut) =>
      unwrap(await updateDocument(d.id, { is_visible_to_client: !d.is_visible_to_client })),
    onSuccess: (_, d) => {
      void message.success(named(d.is_visible_to_client ? t.clients.hidden : t.clients.shown, d));
      void refresh();
    },
    onError,
  });
  return { upload, toggle, onError };
}

type Handlers = {
  canWrite: boolean;
  onToggle: (d: DocumentOut) => void;
  onDownload: (d: DocumentOut) => void;
  onAccess: (d: DocumentOut) => void;
};

function columns({ canWrite, onToggle, onDownload, onAccess }: Handlers): ColumnsType<DocumentOut> {
  return [
    { title: t.clients.type, render: (_, d) => t.clients.types[d.type] ?? d.type },
    { title: t.clients.title, dataIndex: "title" },
    {
      title: t.clients.number,
      dataIndex: "number",
      render: (v: string | null) => v ?? t.common.none,
    },
    {
      title: t.clients.date,
      dataIndex: "doc_date",
      className: "nowrap",
      render: (v: string | null) => (v ? formatDate(v) : t.common.none),
    },
    {
      title: t.clients.visible,
      render: (_, d) => (
        <Switch
          size="small"
          aria-label={named(t.clients.visibleFor, d)}
          disabled={!canWrite}
          checked={d.is_visible_to_client}
          onChange={() => {
            onToggle(d);
          }}
        />
      ),
    },
    { title: t.clients.extract, render: (_, d) => <IngestTag status={d.extract_status} /> },
    {
      title: <ActionsTitle />,
      className: "col-actions",
      render: (_, d) => (
        <RowActions
          label={named(t.clients.documentActions, d)}
          actions={[
            {
              key: "download",
              label: t.clients.download,
              onClick: () => {
                onDownload(d);
              },
            },
            {
              key: "access",
              label: t.clients.access,
              onClick: () => {
                onAccess(d);
              },
            },
          ]}
        />
      ),
    },
  ];
}

type Mutations = ReturnType<typeof useDocumentMutations>;

/** Открыть клиенту — с подтверждением (бот начнёт выдавать документ); скрыть — сразу. */
function useDocumentHandlers(m: Mutations) {
  const confirmDanger = useConfirmDanger();
  const toggle = (d: DocumentOut) => {
    if (d.is_visible_to_client) {
      m.toggle.mutate(d);
      return;
    }
    confirmDanger({
      title: t.confirm.showToClient,
      content: t.confirm.showToClientHint,
      okText: t.confirm.show,
      onOk: () => m.toggle.mutateAsync(d),
    });
  };
  const download = (d: DocumentOut) => {
    void downloadFile(`/api/v1/documents/${String(d.id)}/download`, d.filename).catch(m.onError);
  };
  return { toggle, download };
}

const emptyState = (canWrite: boolean, open: () => void) => ({
  compact: true,
  title: t.clients.documentsEmpty,
  hint: t.clients.documentsEmptyHint,
  ...(canWrite ? { action: { label: t.clients.upload, onClick: open } } : {}),
});

/** Документы клиента: загрузка, видимость клиенту, скачивание и журнал доступа — в «⋯». */
export function ClientDocuments({ clientId, canWrite }: { clientId: number; canWrite: boolean }) {
  const query = useClientDocuments(clientId);
  const [uploading, setUploading] = useState(false);
  const [accessOf, setAccessOf] = useState<DocumentOut | null>(null);
  const m = useDocumentMutations(clientId, () => {
    setUploading(false);
  });
  const { toggle, download } = useDocumentHandlers(m);
  const open = () => {
    setUploading(true);
  };
  const empty = emptyState(canWrite, open);
  return (
    <Flex vertical gap="small">
      {canWrite && query.data?.length ? (
        <Button className="self-start" onClick={open}>
          {t.clients.upload}
        </Button>
      ) : null}
      <PageState query={query} variant="section" empty={query.data?.length === 0 && empty}>
        <Table<DocumentOut>
          rowKey="id"
          size="small"
          dataSource={query.data ?? []}
          scroll={{ x: 760 }}
          pagination={false}
          columns={columns({
            canWrite,
            onToggle: toggle,
            onDownload: download,
            onAccess: setAccessOf,
          })}
        />
      </PageState>
      <UploadDocumentDialog
        open={uploading}
        saving={m.upload.isPending}
        onCancel={() => {
          setUploading(false);
        }}
        onSubmit={(v) => {
          m.upload.mutate(v);
        }}
      />
      <AccessDrawer
        doc={accessOf}
        onClose={() => {
          setAccessOf(null);
        }}
      />
    </Flex>
  );
}
