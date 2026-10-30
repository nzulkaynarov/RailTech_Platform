import { Card } from "antd";
import { Link, useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";

import type { KbDocument } from "../../../shared/api/generated/model";
import { useListKbDocuments } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import type { StatusTone } from "../../../shared/lib/statuses";
import { TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { KbSearch } from "./KbSearch";
import { useKbStateLabels } from "./labels";
import { parseId, withParams } from "./refresh";

/** Ширины колонок: название (гибкая), язык, продукт, индексация, частей, обновлён (UX-1c, S9) */
const COLS = [null, 120, 170, 170, 110, 150] as const;

const INGEST_TONE: Record<KbDocument["ingest_status"], StatusTone> = {
  pending: "default",
  processing: "blue",
  done: "green",
  failed: "red",
};

export function IngestTag({ status }: { status: KbDocument["ingest_status"] }) {
  const { t } = useTranslation("kb");
  return <StatusTag tone={INGEST_TONE[status]}>{t(`ingest.${status}`)}</StatusTag>;
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
    <ScrollRegion label={t("documents.tableScroll")}>
      <table className="pf-kb-table pf-fixed-table" style={{ minWidth: tableMinWidth(COLS, 240) }}>
        <caption className="pf-sr-only">{t("documents.caption")}</caption>
        <TableCols widths={COLS} />
        <thead>
          <tr>
            <th scope="col">{t("documents.columns.title")}</th>
            <th scope="col">{t("documents.columns.language")}</th>
            <th scope="col">{t("documents.columns.product")}</th>
            <th scope="col">{t("documents.columns.status")}</th>
            <th scope="col" className="num">
              {t("documents.columns.chunks")}
            </th>
            <th scope="col">{t("documents.columns.updated")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((doc) => (
            <tr key={doc.id} data-selected={selected === doc.id}>
              <td>
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
                    <StatusTag tone="gold">{t("documents.disabled")}</StatusTag>
                  </>
                )}
              </td>
              <td>{t(`languages.${doc.language}`)}</td>
              <td className="pf-ell" title={doc.product_key ?? undefined}>
                {doc.product_key ?? t("documents.noProduct")}
              </td>
              <td>
                <IngestTag status={doc.ingest_status} />
              </td>
              <td className="num">{doc.chunk_count}</td>
              <td>{date(doc.updated_at, "datetime")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
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
