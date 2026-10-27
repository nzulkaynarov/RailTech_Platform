import { Card, Pagination, Segmented } from "antd";
import { Link, useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { KbGap, KbGapStatus } from "../../../shared/api/generated/model";
import { useListKbGaps } from "../../../shared/api/generated/platform-bff";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { GAP_STATUSES, PAGE_SIZE, gapPageParam, gapStatusParam, leadNumber } from "./gaps";
import { useKbStateLabels } from "./labels";
import { parseId, withParams } from "./refresh";

export function LeadRef({ id }: { id: number | null }) {
  const { me } = useAuth();
  const { t } = useTranslation("kb");
  if (id === null) return <>{t("gaps.noLead")}</>;
  const number = leadNumber(id);
  if (!canSee(me, { resource: "crm.leads" })) return <>{number}</>;
  return (
    <Link className="pf-focusable" to={`/crm/leads/${number}`}>
      {number}
    </Link>
  );
}

function GapsTable({ items, status }: { items: readonly KbGap[]; status: KbGapStatus }) {
  const { t } = useTranslation("kb");
  const [params] = useSearchParams();
  const selected = parseId(params.get("gap"));
  if (items.length === 0) {
    return (
      <EmptyState title={t(`gaps.empty.${status}.title`)} text={t(`gaps.empty.${status}.text`)} />
    );
  }
  return (
    <ScrollRegion label={t("gaps.tableScroll")}>
      <table className="pf-kb-table">
        <caption className="pf-sr-only">{t("gaps.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("gaps.columns.question")}</th>
            <th scope="col" className="num">
              {t("gaps.columns.occurrences")}
            </th>
            <th scope="col">{t("gaps.columns.language")}</th>
            <th scope="col" className="num">
              {t("gaps.columns.score")}
            </th>
            <th scope="col">{t("gaps.columns.lead")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((gap) => (
            <tr key={gap.id} data-selected={selected === gap.id}>
              <td>
                <Link
                  className="pf-focusable pf-kb-doc-link"
                  to={withParams(params, { gap: String(gap.id), new: null, panel: "open" })}
                  aria-label={t("gaps.open", { question: gap.question })}
                  aria-current={selected === gap.id ? "true" : undefined}
                >
                  {gap.question}
                </Link>
              </td>
              <td className="num">{gap.occurrences}</td>
              <td>{t(`languages.${gap.language}`)}</td>
              <td className="num">{gap.best_score === null ? "—" : gap.best_score.toFixed(2)}</td>
              <td>
                <LeadRef id={gap.lead_id} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/** Вопросы без ответа: закрыть документом, игнорировать, вернуть; карточка пробела — в боковом окне. */
export function GapsView() {
  const { t } = useTranslation("kb");
  const [params, setParams] = useSearchParams();
  const status = gapStatusParam(params.get("status"));
  const page = gapPageParam(params.get("page"));
  const query = useListKbGaps({ status, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const labels = useKbStateLabels();
  return (
    <section aria-labelledby="pf-kb-gaps">
      <Card
        styles={{ body: { padding: 0 } }}
        title={
          <h2 className="pf-kb-section-title" id="pf-kb-gaps">
            {t("gaps.title")}
          </h2>
        }
        extra={
          <Segmented
            aria-label={t("gaps.status")}
            value={status}
            options={GAP_STATUSES.map((value) => ({ value, label: t(`gaps.statuses.${value}`) }))}
            onChange={(value) => {
              setParams(
                (prev) => {
                  const next = new URLSearchParams(prev);
                  next.set("status", value);
                  next.delete("gap");
                  next.delete("page");
                  return next;
                },
                { replace: true },
              );
            }}
          />
        }
      >
        <p className="pf-fp-sub pf-kb-lead">{t("gaps.hint")}</p>
        <QueryState query={query} labels={labels}>
          {(data) => (
            <>
              <GapsTable items={data.items} status={status} />
              {data.total > PAGE_SIZE ? (
                <div className="pf-kb-pager">
                  <Pagination
                    size="small"
                    current={page}
                    pageSize={PAGE_SIZE}
                    total={data.total}
                    showSizeChanger={false}
                    onChange={(next) => {
                      setParams(
                        (prev) => {
                          const copy = new URLSearchParams(prev);
                          copy.set("page", String(next));
                          copy.delete("gap");
                          return copy;
                        },
                        { replace: true },
                      );
                    }}
                  />
                </div>
              ) : null}
              <StatusLine total={data.total} />
            </>
          )}
        </QueryState>
      </Card>
    </section>
  );
}

function StatusLine({ total }: { total: number }) {
  const { t } = useTranslation("kb");
  return (
    <p className="pf-hint pf-kb-lead" role="status">
      {t("gaps.total", { count: total })}
    </p>
  );
}

export function GapStatusTag({ status }: { status: KbGapStatus }) {
  const { t } = useTranslation("kb");
  const tone = status === "open" ? "gold" : status === "resolved" ? "green" : "default";
  return <StatusTag tone={tone}>{t(`gaps.statuses.${status}`)}</StatusTag>;
}
