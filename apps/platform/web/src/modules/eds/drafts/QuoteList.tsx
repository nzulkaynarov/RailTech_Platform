import { useInfiniteQuery } from "@tanstack/react-query";
import { Button, Card, Segmented, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { QuoteApprovalRow } from "../../../shared/api/generated/model";
import {
  getListQuoteApprovalsQueryKey,
  listQuoteApprovals,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { withParams } from "../inbox/api";
import { DocumentStatusTag } from "../documents/status";
import { type Scope, quotePath, scopeOf } from "./api";
import { ApprovalSlot } from "./ApprovalPanel";
import { useStateLabels } from "./labels";

const PAGE = 25;

function useSelect() {
  const [params] = useSearchParams();
  const { mobile } = useViewport();
  // Строка открывает КП в боковом окне без перехода; на телефоне — лист на весь экран.
  return (id: string) =>
    withParams(params, {
      quote: id,
      tab: "approve",
      panel: mobile ? null : "open",
      sheet: mobile ? "approve" : null,
    });
}

function Total({ row }: { row: QuoteApprovalRow }) {
  if (!row.total) return <>—</>;
  return (
    <MoneyText
      value={row.total.amount}
      {...(row.total.currency === "UZS" ? {} : { currency: row.total.currency })}
    />
  );
}

function Rows({
  items,
  selected,
}: {
  items: readonly QuoteApprovalRow[];
  selected: string | null;
}) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  const { mobile } = useViewport();
  const select = useSelect();
  const navigate = useNavigate();

  if (mobile) {
    return (
      <ul className="pf-dec-cards" aria-label={t("list.caption")}>
        {items.map((row) => (
          <li key={row.id} data-selected={selected === row.id}>
            <div className="pf-dec-card-head">
              <Link
                className="pf-focusable pf-dec-number"
                to={select(row.id)}
                aria-label={t("list.select", { number: row.number })}
              >
                {row.number}
              </Link>
              <DocumentStatusTag kind="quote" status={row.status} />
            </div>
            <p className="pf-dec-card-subject">{row.client_name ?? "—"}</p>
            <p className="pf-hint">
              {row.request_number ?? "—"}
              {row.total ? (
                <>
                  {" · "}
                  <Total row={row} />
                </>
              ) : null}
            </p>
            <div className="pf-dec-card-foot">
              <span className="pf-hint">{date(row.created_at, "datetime")}</span>
              <LinkButton
                size="small"
                to={quotePath(row.id)}
                aria-label={t("list.openLabel", { number: row.number })}
              >
                {t("list.open")}
              </LinkButton>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ScrollRegion label={t("list.scroll")}>
      <table className="pf-dec-table">
        <caption className="pf-sr-only">{t("list.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("list.columns.number")}</th>
            <th scope="col">{t("list.columns.request")}</th>
            <th scope="col">{t("list.columns.client")}</th>
            <th scope="col" className="pf-dec-right">
              {t("list.columns.total")}
            </th>
            <th scope="col">{t("list.columns.due")}</th>
            <th scope="col">{t("list.columns.received")}</th>
            <th scope="col">{t("list.columns.status")}</th>
            <th scope="col">
              <span className="pf-sr-only">{t("list.columns.action")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr
              key={row.id}
              data-row
              data-selected={selected === row.id}
              onClick={(event) => {
                // Клик по строке — КП в боковом окне; ссылки и кнопки внутри работают сами.
                if ((event.target as HTMLElement).closest("a,button")) return;
                void navigate(select(row.id), { replace: true });
              }}
            >
              <td className="pf-num">
                <Link
                  className="pf-focusable pf-dec-number"
                  to={select(row.id)}
                  replace
                  aria-label={t("list.select", { number: row.number })}
                  aria-current={selected === row.id ? "true" : undefined}
                >
                  {row.number}
                </Link>
                <div className="pf-hint">{t("list.version", { version: row.version })}</div>
              </td>
              <td className="pf-num">{row.request_number ?? "—"}</td>
              <td>{row.client_name ?? "—"}</td>
              <td className="pf-dec-right">
                <Total row={row} />
              </td>
              <td className="pf-num">{row.due ? date(row.due) : "—"}</td>
              <td className="pf-num">{date(row.created_at, "datetime")}</td>
              <td>
                <DocumentStatusTag kind="quote" status={row.status} />
              </td>
              <td>
                <LinkButton
                  size="small"
                  to={quotePath(row.id)}
                  aria-label={t("list.openLabel", { number: row.number })}
                >
                  {t("list.open")}
                </LinkButton>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/**
 * EDS · КП на одобрение (SPEC-v3 §7.3): список КП, текущий шаг которых ждёт директора («На моём шаге»), или все КП, которые EDS
 * показывает сотруднику (менеджер — только чтение, без суммы и маржи); КП — в боковом окне «Одобрение».
 */
export function QuoteList() {
  const { t } = useTranslation(["quotes", "modules"]);
  const { me } = useAuth();
  const mayDecide = canEdit(me, "eds.drafts");
  const [params, setParams] = useSearchParams();
  const labels = useStateLabels();
  const scope = scopeOf(params.get("scope"), mayDecide ? "mine" : "all");
  const selected = params.get("quote");
  const title = t("modules:eds.sections.drafts");
  useDocumentTitle(title);

  const listParams = { scope, limit: PAGE };
  const query = useInfiniteQuery({
    queryKey: getListQuoteApprovalsQueryKey(listParams),
    queryFn: ({ pageParam }) =>
      listQuoteApprovals({ ...listParams, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = query.data?.pages.flatMap((page) => page.items) ?? [];

  const setScope = (value: Scope) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("scope", value);
        next.delete("quote");
        next.delete("sheet");
        return next;
      },
      { replace: true },
    );
  };

  let body;
  if (query.isPending) {
    body = <Skeleton active paragraph={{ rows: 5 }} title={false} />;
  } else if (query.isError) {
    const error = query.error;
    const text =
      error instanceof ApiError && error.status === 403
        ? error.details["reason"] === "eds_not_granted"
          ? { title: t("quotes:state.notGranted.title"), text: t("quotes:state.notGranted.text") }
          : labels.forbidden
        : error instanceof ApiError && error.status >= 500
          ? labels.unavailable
          : labels.loadError;
    body = (
      <EmptyState
        title={text.title}
        text={text.text}
        action={
          error instanceof ApiError && error.status === 403 ? undefined : (
            <Button
              onClick={() => {
                void query.refetch();
              }}
            >
              {labels.retry}
            </Button>
          )
        }
      />
    );
  } else if (rows.length === 0) {
    body = (
      <EmptyState
        title={t(`quotes:list.empty.${scope}.title`)}
        text={t(`quotes:list.empty.${scope}.text`)}
        action={
          scope === "mine" ? (
            <Button
              onClick={() => {
                setScope("all");
              }}
            >
              {t("quotes:list.empty.mine.action")}
            </Button>
          ) : (
            <Button
              onClick={() => {
                void query.refetch();
              }}
            >
              {t("quotes:list.empty.all.action")}
            </Button>
          )
        }
      />
    );
  } else {
    body = (
      <>
        <Rows items={rows} selected={selected} />
        {query.hasNextPage ? (
          <div className="pf-dec-pager">
            <Button
              loading={query.isFetchingNextPage}
              onClick={() => {
                void query.fetchNextPage();
              }}
            >
              {t("quotes:list.more")}
            </Button>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="pf-dec-page">
      <PageHeader title={title} subtitle={t("quotes:list.subtitle")} />
      {mayDecide ? (
        <Segmented
          aria-label={t("quotes:list.scope.label")}
          value={scope}
          options={[
            { value: "mine", label: t("quotes:list.scope.mine") },
            { value: "all", label: t("quotes:list.scope.all") },
          ]}
          onChange={(value) => {
            setScope(value as Scope);
          }}
        />
      ) : null}
      <Card styles={{ body: { padding: 0 } }}>{body}</Card>
      {selected ? <ApprovalSlot quoteRef={selected} brief /> : null}
    </div>
  );
}
