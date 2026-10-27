import { App, Button, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import type { KbGap } from "../../../shared/api/generated/model";
import {
  useIgnoreKbGap,
  useListKbDocuments,
  useListKbGaps,
  useReopenKbGap,
  useResolveKbGap,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ActionToggle, ErrorNote, FormField, QueryState } from "../../../shared/ui/FormParts";
import { ManualForm } from "./CreateDocumentPanel";
import { kbErrorText } from "./errors";
import { PAGE_SIZE, gapPageParam, gapStatusParam } from "./gaps";
import { GapStatusTag, LeadRef } from "./GapsView";
import { useKbStateLabels } from "./labels";
import { useRefreshKb, withParams } from "./refresh";

type Action = "create" | "link" | "ignore" | "reopen" | null;

function useClose() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  return () => {
    void navigate({ search: withParams(params, { gap: null }) }, { replace: true });
  };
}

function LinkForm({ gap, onDone }: { gap: KbGap; onDone: () => void }) {
  const { t, i18n } = useTranslation("kb");
  const { message } = App.useApp();
  const refresh = useRefreshKb();
  const documents = useListKbDocuments({ active: true });
  const [documentId, setDocumentId] = useState<number | null>(null);
  const resolve = useResolveKbGap({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("gapPanel.link.done"));
        onDone();
      },
    },
  });
  return (
    <form
      className="pf-fp-form"
      aria-label={t("gapPanel.link.button")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (documentId !== null) resolve.mutate({ id: gap.id, data: { document_id: documentId } });
      }}
    >
      <FormField id="kb-gap-document" label={t("gapPanel.link.document")}>
        <Select
          id="kb-gap-document"
          showSearch
          loading={documents.isPending}
          optionFilterProp="label"
          value={documentId}
          placeholder={t("gapPanel.link.placeholder")}
          options={(documents.data?.items ?? []).map((d) => ({ value: d.id, label: d.title }))}
          onChange={setDocumentId}
        />
      </FormField>
      <Consequence
        items={[t("gapPanel.link.step1"), t("gapPanel.link.step2"), t("gapPanel.link.step3")]}
      />
      <ErrorNote message={resolve.isError ? kbErrorText(t, resolve.error, i18n.language) : null} />
      <div className="pf-fp-row">
        <Button
          type="primary"
          htmlType="submit"
          loading={resolve.isPending}
          disabled={documentId === null}
        >
          {t("gapPanel.link.submit")}
        </Button>
      </div>
    </form>
  );
}

function SimpleAction({
  gap,
  kind,
  onDone,
}: {
  gap: KbGap;
  kind: "ignore" | "reopen";
  onDone: () => void;
}) {
  const { t, i18n } = useTranslation("kb");
  const { message } = App.useApp();
  const refresh = useRefreshKb();
  const options = {
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t(`gapPanel.${kind}.done`));
        onDone();
      },
    },
  };
  const ignore = useIgnoreKbGap(options);
  const reopen = useReopenKbGap(options);
  const action = kind === "ignore" ? ignore : reopen;
  return (
    <form
      className="pf-fp-form"
      aria-label={t(`gapPanel.${kind}.button`)}
      onSubmit={(event) => {
        event.preventDefault();
        action.mutate({ id: gap.id });
      }}
    >
      <Consequence
        items={[t(`gapPanel.${kind}.step1`), t(`gapPanel.${kind}.step2`), t("gapPanel.stepAudit")]}
      />
      <ErrorNote message={action.isError ? kbErrorText(t, action.error, i18n.language) : null} />
      <div className="pf-fp-row">
        <Button
          type="primary"
          danger={kind === "ignore"}
          htmlType="submit"
          loading={action.isPending}
        >
          {t(`gapPanel.${kind}.submit`)}
        </Button>
      </div>
    </form>
  );
}

function GapBody({ gap, editable }: { gap: KbGap; editable: boolean }) {
  const { t } = useTranslation("kb");
  const { date } = useFormat();
  const close = useClose();
  const [open, setOpen] = useState<Action>(null);
  const toggle = (action: Exclude<Action, null>) => (next: boolean) => {
    setOpen(next ? action : null);
  };
  return (
    <div className="pf-fp-stack">
      <div className="pf-kb-panel-head">
        <h3 className="pf-fp-title">{gap.question}</h3>
        <div className="pf-fp-row">
          <GapStatusTag status={gap.status} />
        </div>
      </div>
      <DefinitionList
        items={[
          { label: t("gapPanel.fields.occurrences"), value: gap.occurrences },
          { label: t("gapPanel.fields.language"), value: t(`languages.${gap.language}`) },
          {
            label: t("gapPanel.fields.score"),
            value: gap.best_score === null ? null : gap.best_score.toFixed(2),
          },
          { label: t("gapPanel.fields.lead"), value: <LeadRef id={gap.lead_id} /> },
          { label: t("gapPanel.fields.created"), value: date(gap.created_at, "datetime") },
          { label: t("gapPanel.fields.updated"), value: date(gap.updated_at, "datetime") },
        ]}
      />
      {!editable ? (
        <p className="pf-hint">{t("common.readOnly")}</p>
      ) : gap.status === "open" ? (
        <section className="pf-fp-block" aria-labelledby="pf-kb-gap-actions">
          <h4 id="pf-kb-gap-actions">{t("panel.actions")}</h4>
          <ActionToggle
            label={t("gapPanel.create.button")}
            open={open === "create"}
            onToggle={toggle("create")}
          >
            <ManualForm
              draft={{
                title: gap.question.slice(0, 200),
                language: gap.language,
                markdown: `## ${gap.question}\n\n`,
                gapId: gap.id,
              }}
            />
          </ActionToggle>
          <ActionToggle
            label={t("gapPanel.link.button")}
            open={open === "link"}
            onToggle={toggle("link")}
          >
            <LinkForm gap={gap} onDone={close} />
          </ActionToggle>
          <ActionToggle
            danger
            label={t("gapPanel.ignore.button")}
            open={open === "ignore"}
            onToggle={toggle("ignore")}
          >
            <SimpleAction gap={gap} kind="ignore" onDone={close} />
          </ActionToggle>
        </section>
      ) : (
        <section className="pf-fp-block" aria-labelledby="pf-kb-gap-actions">
          <h4 id="pf-kb-gap-actions">{t("panel.actions")}</h4>
          <ActionToggle
            label={t("gapPanel.reopen.button")}
            open={open === "reopen"}
            onToggle={toggle("reopen")}
          >
            <SimpleAction gap={gap} kind="reopen" onDone={close} />
          </ActionToggle>
        </section>
      )}
    </div>
  );
}

/** Карточка пробела в боковом окне: вопрос, сколько раз спросили, действия с «Что произойдёт». */
export function GapPanel({ id, editable }: { id: number; editable: boolean }) {
  const { t } = useTranslation("kb");
  const [params] = useSearchParams();
  const status = gapStatusParam(params.get("status"));
  const page = gapPageParam(params.get("page"));
  // Пробел берётся из списка своего статуса (отдельного запроса «один пробел» в CRM нет); тот же запрос, что у таблицы.
  const query = useListKbGaps({ status, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const labels = useKbStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(data) => {
        const gap = data.items.find((g) => g.id === id);
        return gap ? (
          <GapBody key={gap.id} gap={gap} editable={editable} />
        ) : (
          <p className="pf-hint">{t("gapPanel.notFound")}</p>
        );
      }}
    </QueryState>
  );
}
