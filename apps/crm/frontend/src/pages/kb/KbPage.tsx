import { Button, Space } from "antd";
import { useState } from "react";

import { useKbDocuments } from "../../api/adminQueries";
import type { KbDocumentOut } from "../../api/generated/model";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { useProductNames } from "../../hooks/useProductNames";
import { t } from "../../i18n/ru";
import { KbChunksDrawer } from "./KbChunksDrawer";
import { ManualDialog, UploadDialog } from "./KbDialogs";
import { KbTable } from "./KbTable";
import { TestSearch } from "./TestSearch";
import { useKbMutations } from "./useKbMutations";
import "../admin.css";

type Dialog = "upload" | "manual" | null;

function CreateButtons({ onOpen }: { onOpen: (dialog: Dialog) => void }) {
  return (
    <Space wrap>
      <Button
        type="primary"
        onClick={() => {
          onOpen("upload");
        }}
      >
        {t.kb.upload}
      </Button>
      <Button
        onClick={() => {
          onOpen("manual");
        }}
      >
        {t.kb.manual}
      </Button>
    </Space>
  );
}

/** База знаний (admin, PLAN Фаза 5): документы, загрузка, индексация, фрагменты, тест поиска. */
export function KbPage() {
  const query = useKbDocuments();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [chunksOf, setChunksOf] = useState<KbDocumentOut | null>(null);
  const productName = useProductNames();
  const m = useKbMutations(() => {
    setDialog(null);
  });
  const confirmDanger = useConfirmDanger();
  const toggle = (d: KbDocumentOut) => {
    if (!d.is_active) {
      m.toggle.mutate(d);
      return;
    }
    confirmDanger({
      title: t.confirm.deactivateKb,
      content: t.confirm.deactivateKbHint,
      okText: t.confirm.deactivate,
      onOk: () => m.toggle.mutateAsync(d),
    });
  };
  const close = () => {
    setDialog(null);
  };

  return (
    <PageBody>
      <PageHeader title={t.page.kb} extra={<CreateButtons onOpen={setDialog} />} />
      <TestSearch />
      <PageState
        query={query}
        empty={query.data?.length === 0 && { title: t.kb.empty, hint: t.kb.emptyHint }}
      >
        <KbTable
          data={query.data ?? []}
          loading={query.isFetching && !query.data}
          productName={productName}
          onOpen={setChunksOf}
          onToggle={toggle}
          onReingest={(d) => {
            m.reingest.mutate(d);
          }}
        />
      </PageState>
      <UploadDialog
        open={dialog === "upload"}
        saving={m.upload.isPending}
        onCancel={close}
        onSubmit={(v) => {
          m.upload.mutate(v);
        }}
      />
      <ManualDialog
        open={dialog === "manual"}
        saving={m.manual.isPending}
        onCancel={close}
        onSubmit={(v) => {
          m.manual.mutate(v);
        }}
      />
      <KbChunksDrawer
        doc={chunksOf}
        onClose={() => {
          setChunksOf(null);
        }}
      />
    </PageBody>
  );
}
