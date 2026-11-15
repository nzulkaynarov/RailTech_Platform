import { Card } from "antd";
import { Link, useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";

import type { KbDocument } from "../../../shared/api/generated/model";
import { useListKbDocuments } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { KbSearch } from "./KbSearch";
import { useKbStateLabels } from "./labels";
import { parseId, withParams } from "./refresh";

export function IngestTag({ status }: { status: KbDocument["ingest_status"] }) {
  const { t } = useTranslation("kb");
  return (
    <StatusTag kind="kbIngest" status={status}>
      {t(`ingest.${status}`)}
    </StatusTag>
  );
}

function DocumentsTable({ items, editable }: { items: readonly KbDocument[]; editable: boolean }) {
  const { t } = useTranslation("kb");
  const { date } = useFormat();
  const [params] = useSearchParams();
  const selected = parseId(params.get("doc"));
  if (items.length === 0) {
    return (
      <EmptyState
        title={t("documents.empty.title")}
        text={t("documents.empty.text")}
        action={
          editable ? (
            <LinkButton type="primary" to={withParams(params, { new: "upload", panel: "open" })}>
              {t("documents.upload")}
            </LinkButton>
          ) : undefined
        }
      />
    );
  }
  return (
    <DataTable<KbDocument>
      tableId="crm.kb.documents"
      caption={t("documents.caption")}
      scrollLabel={t("documents.tableScroll")}
      className="pf-kb-table"
      flexMin={240}
      rows={items}
      rowKey={(doc) => String(doc.id)}
      rowAttrs={(doc) => ({ "data-selected": selected === doc.id })}
      columns={[
        {
          id: "title",
          header: t("documents.columns.title"),
          width: null,
          cell: (doc) => (
            <>
              <Link
                className="pf-focusable pf-kb-doc-link"
                to={withParams(params, { doc: String(doc.id), new: null, panel: "open" })}
                aria-label={t("documents.open", { title: doc.title })}
                aria-current={selected === doc.id ? "true" : undefined}
              >
                {doc.title}
              </Link>
              {doc.is_active ? null : (
                <>
                  {" "}
                  <StatusTag kind="activity" status="inactive">
                    {t("documents.disabled")}
                  </StatusTag>
                </>
              )}
            </>
          ),
        },
        {
          id: "language",
          header: t("documents.columns.language"),
          width: 120,
          cell: (doc) => t(`languages.${doc.language}`),
        },
        {
          id: "product",
          header: t("documents.columns.product"),
          width: 170,
          cellClassName: "pf-ell",
          cellTitle: (doc) => doc.product_key ?? undefined,
          cell: (doc) => doc.product_key ?? t("documents.noProduct"),
        },
        {
          id: "status",
          header: t("documents.columns.status"),
          width: 170,
          cell: (doc) => <IngestTag status={doc.ingest_status} />,
        },
        {
          id: "chunks",
          header: t("documents.columns.chunks"),
          width: 110,
          numeric: true,
          cell: (doc) => doc.chunk_count,
        },
        {
          id: "updated",
          header: t("documents.columns.updated"),
          width: 150,
          cell: (doc) => date(doc.updated_at, "datetime"),
        },
      ]}
    />
  );
}

/** Документы базы знаний: «Что найдёт бот» и список с состоянием индексации; карточка документа — в боковом окне. */
export function DocumentsView({ editable }: { editable: boolean }) {
  const { t } = useTranslation("kb");
  const query = useListKbDocuments();
  const labels = useKbStateLabels();
  return (
    <>
      <KbSearch />
      <section aria-labelledby="pf-kb-documents">
        <Card
          styles={{ body: { padding: 0 } }}
          title={
            <h2 className="pf-kb-section-title" id="pf-kb-documents">
              {t("documents.title")}
            </h2>
          }
        >
          <QueryState query={query} labels={labels} rows={10}>
            {(data) => <DocumentsTable items={data.items} editable={editable} />}
          </QueryState>
        </Card>
      </section>
    </>
  );
}
