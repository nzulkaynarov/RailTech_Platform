import { Modal, Segmented, Select } from "antd";
import { useState } from "react";

import { useKbDocuments, useKbGaps } from "../../api/adminQueries";
import type { KbGapOut, ListKbGapsStatus } from "../../api/generated/model";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { ManualDialog, type ManualValues } from "../kb/KbDialogs";
import { GapsTable } from "./GapsTable";
import { useGapActions } from "./useGapActions";
import "../admin.css";

const STATUSES = (["open", "resolved", "ignored"] as const).map((v) => ({
  value: v,
  label: t.gaps.statuses[v],
}));

type LinkProps = {
  gap: KbGapOut | null;
  saving: boolean;
  onCancel: () => void;
  onLink: (gap: KbGapOut, documentId: number) => void;
};

function LinkGapDialog({ gap, saving, onCancel, onLink }: LinkProps) {
  const docs = useKbDocuments();
  const [documentId, setDocumentId] = useState<number | null>(null);
  return (
    <Modal
      open={gap !== null}
      title={t.gaps.link}
      okText={t.gaps.link}
      confirmLoading={saving}
      okButtonProps={{ disabled: documentId === null }}
      onCancel={onCancel}
      onOk={() => {
        if (gap && documentId !== null) onLink(gap, documentId);
      }}
      destroyOnHidden
    >
      <Select
        showSearch
        aria-label={t.gaps.document}
        className="full-width"
        placeholder={t.gaps.document}
        optionFilterProp="label"
        value={documentId}
        onChange={setDocumentId}
        options={(docs.data ?? [])
          .filter((d) => d.is_active)
          .map((d) => ({ value: d.id, label: d.title }))}
      />
    </Modal>
  );
}

const draftOf = (gap: KbGapOut | null): Partial<ManualValues> =>
  gap
    ? {
        title: gap.question.slice(0, 200),
        language: gap.language as ManualValues["language"],
        markdown: `## ${gap.question}\n\n`,
      }
    : {};

type GapDialogsProps = {
  creating: KbGapOut | null;
  linking: KbGapOut | null;
  m: ReturnType<typeof useGapActions>;
  close: () => void;
};

function GapDialogs({ creating, linking, m, close }: GapDialogsProps) {
  return (
    <>
      <ManualDialog
        open={creating !== null}
        saving={m.create.isPending}
        initial={draftOf(creating)}
        onCancel={() => {
          close();
        }}
        onSubmit={(v) => {
          if (creating) m.create.mutate({ ...v, gapId: creating.id });
        }}
      />
      <LinkGapDialog
        gap={linking}
        saving={m.act.isPending}
        onCancel={() => {
          close();
        }}
        onLink={(gap, documentId) => {
          m.act.mutate({ kind: "link", gap, documentId });
        }}
      />
    </>
  );
}

/** Пробелы KB (сценарий C4): вопросы без ответа → документ, привязка или «скрыть». */
export function GapsPage() {
  const [status, setStatus] = useState<ListKbGapsStatus>("open");
  const query = useKbGaps({ status, limit: 200 });
  const confirmDanger = useConfirmDanger();
  const [creating, setCreating] = useState<KbGapOut | null>(null);
  const [linking, setLinking] = useState<KbGapOut | null>(null);
  const m = useGapActions(() => {
    setCreating(null);
    setLinking(null);
  });
  const items = query.data?.items ?? [];
  const ignore = (gap: KbGapOut) => {
    confirmDanger({
      title: t.gaps.ignoreTitle,
      content: t.gaps.ignoreHint,
      okText: t.gaps.ignore,
      onOk: () => m.act.mutateAsync({ kind: "ignore", gap }),
    });
  };

  return (
    <PageBody>
      <PageHeader title={t.page.gaps} />
      <Segmented
        aria-label={t.gaps.status}
        value={status}
        onChange={setStatus}
        options={STATUSES}
      />
      <PageState
        query={query}
        empty={
          Boolean(query.data) &&
          !items.length && { title: t.gaps.empty[status] ?? "", hint: t.gaps.emptyHint[status] }
        }
      >
        <GapsTable
          data={items}
          loading={query.isFetching && !query.data}
          onCreate={setCreating}
          onLink={setLinking}
          onIgnore={ignore}
          onReopen={(gap) => {
            m.act.mutate({ kind: "reopen", gap });
          }}
        />
      </PageState>
      <GapDialogs
        creating={creating}
        linking={linking}
        m={m}
        close={() => {
          setCreating(null);
          setLinking(null);
        }}
      />
    </PageBody>
  );
}
