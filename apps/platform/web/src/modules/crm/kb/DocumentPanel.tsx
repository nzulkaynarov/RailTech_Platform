import { App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useGetKbDocument,
  useListKbChunks,
  useReingestKbDocument,
  useUpdateKbDocument,
} from "../../../shared/api/generated/platform-bff";
import type { KbDocument } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ActionToggle, ErrorNote, QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { IngestTag } from "./DocumentsView";
import { kbErrorText } from "./errors";
import { useKbStateLabels } from "./labels";
import { useRefreshKb } from "./refresh";

type Action = "toggle" | "reingest" | null;

function Chunks({ id }: { id: number }) {
  const { t } = useTranslation("kb");
  const query = useListKbChunks(id);
  const labels = useKbStateLabels();
  return (
    <section className="pf-fp-block" aria-labelledby="pf-kb-chunks">
      <h4 id="pf-kb-chunks">{t("panel.chunks.title")}</h4>
      <p className="pf-fp-sub">{t("panel.chunks.hint")}</p>
      <QueryState query={query} labels={labels} level={3} compact>
        {(data) =>
          data.items.length === 0 ? (
            <p className="pf-hint">{t("panel.chunks.empty")}</p>
          ) : (
            <ol className="pf-kb-hits" aria-label={t("panel.chunks.title")}>
              {data.items.map((chunk) => (
                <li key={chunk.id}>
                  <div className="pf-kb-hit-head">
                    <strong>{t("panel.chunks.number", { number: chunk.position + 1 })}</strong>
                    {chunk.heading_path ? (
                      <span className="pf-hint">{chunk.heading_path}</span>
                    ) : null}
                    <span className="pf-hint">
                      {t("panel.chunks.tokens", { count: chunk.token_count })}
                    </span>
                  </div>
                  <p className="pf-kb-hit-text">{chunk.content}</p>
                </li>
              ))}
            </ol>
          )
        }
      </QueryState>
    </section>
  );
}

function Actions({ doc }: { doc: KbDocument }) {
  const { t, i18n } = useTranslation("kb");
  const { message } = App.useApp();
  const refresh = useRefreshKb();
  const [open, setOpen] = useState<Action>(null);
  const update = useUpdateKbDocument({
    mutation: {
      onSuccess: () => {
        refresh();
        setOpen(null);
        void message.success(t(doc.is_active ? "panel.toggle.doneOff" : "panel.toggle.doneOn"));
      },
    },
  });
  const reingest = useReingestKbDocument({
    mutation: {
      onSuccess: () => {
        refresh();
        setOpen(null);
        void message.success(t("panel.reingest.done"));
      },
    },
  });
  const turnOff = doc.is_active;
  return (
    <section className="pf-fp-block" aria-labelledby="pf-kb-actions">
      <h4 id="pf-kb-actions">{t("panel.actions")}</h4>
      <ActionToggle
        danger={turnOff}
        label={t(turnOff ? "panel.toggle.off" : "panel.toggle.on")}
        open={open === "toggle"}
        onToggle={(next) => {
          setOpen(next ? "toggle" : null);
        }}
      >
        <form
          className="pf-fp-form"
          aria-label={t(turnOff ? "panel.toggle.off" : "panel.toggle.on")}
          onSubmit={(event) => {
            event.preventDefault();
            update.mutate({ id: doc.id, data: { is_active: !doc.is_active } });
          }}
        >
          <Consequence
            items={[
              t(turnOff ? "panel.toggle.offStep1" : "panel.toggle.onStep1"),
              t(turnOff ? "panel.toggle.offStep2" : "panel.toggle.onStep2"),
              t("panel.toggle.step3"),
            ]}
          />
          <ErrorNote
            message={update.isError ? kbErrorText(t, update.error, i18n.language) : null}
          />
          <div className="pf-fp-row">
            <Button type="primary" danger={turnOff} htmlType="submit" loading={update.isPending}>
              {t(turnOff ? "panel.toggle.submitOff" : "panel.toggle.submitOn")}
            </Button>
          </div>
        </form>
      </ActionToggle>
      <ActionToggle
        label={t("panel.reingest.button")}
        open={open === "reingest"}
        onToggle={(next) => {
          setOpen(next ? "reingest" : null);
        }}
      >
        <form
          className="pf-fp-form"
          aria-label={t("panel.reingest.button")}
          onSubmit={(event) => {
            event.preventDefault();
            reingest.mutate({ id: doc.id });
          }}
        >
          <Consequence
            items={[
              t("panel.reingest.step1"),
              t("panel.reingest.step2"),
              t("panel.reingest.step3"),
            ]}
          />
          <ErrorNote
            message={reingest.isError ? kbErrorText(t, reingest.error, i18n.language) : null}
          />
          <div className="pf-fp-row">
            <Button type="primary" htmlType="submit" loading={reingest.isPending}>
              {t("panel.reingest.submit")}
            </Button>
          </div>
        </form>
      </ActionToggle>
    </section>
  );
}

function DocumentBody({ doc, editable }: { doc: KbDocument; editable: boolean }) {
  const { t } = useTranslation("kb");
  const { date } = useFormat();
  return (
    <div className="pf-fp-stack">
      <div className="pf-kb-panel-head">
        <h3 className="pf-fp-title">{doc.title}</h3>
        <div className="pf-fp-row">
          <IngestTag status={doc.ingest_status} />
          {doc.is_active ? (
            <StatusTag kind="activity" status="active">
              {t("panel.active")}
            </StatusTag>
          ) : (
            <StatusTag kind="activity" status="inactive">
              {t("documents.disabled")}
            </StatusTag>
          )}
        </div>
      </div>
      {doc.ingest_error ? (
        <p className="pf-kb-error" role="status">
          {t("panel.ingestError", { error: doc.ingest_error })}
        </p>
      ) : null}
      <DefinitionList
        items={[
          { label: t("panel.fields.language"), value: t(`languages.${doc.language}`) },
          { label: t("panel.fields.product"), value: doc.product_key },
          { label: t("panel.fields.source"), value: t(`source.${doc.source_type}`) },
          { label: t("panel.fields.version"), value: doc.version },
          { label: t("panel.fields.chunks"), value: doc.chunk_count },
          { label: t("panel.fields.created"), value: date(doc.created_at, "datetime") },
          { label: t("panel.fields.updated"), value: date(doc.updated_at, "datetime") },
        ]}
      />
      {editable ? <Actions doc={doc} /> : <p className="pf-hint">{t("common.readOnly")}</p>}
      <Chunks id={doc.id} />
    </div>
  );
}

/** Карточка документа в боковом окне: реквизиты, действия с «Что произойдёт», фрагменты, как их видит поиск бота. */
export function DocumentPanel({ id, editable }: { id: number; editable: boolean }) {
  const query = useGetKbDocument(id);
  const labels = useKbStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(doc) => <DocumentBody doc={doc} editable={editable} />}
    </QueryState>
  );
}
