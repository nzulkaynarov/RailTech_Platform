import { useInfiniteQuery } from "@tanstack/react-query";
import { Button, Card, Segmented, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { MemoApprovalRow } from "../../../shared/api/generated/model";
import {
  getListMemoApprovalsQueryKey,
  listMemoApprovals,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { type Scope, scopeOf } from "../drafts/api";
import { withParams } from "../inbox/api";
import { AgreeSlot } from "./AgreePanel";
import { memoPath } from "./api";
import { useStateLabels } from "./labels";
import { mayDecideMemos } from "./model";

const PAGE = 25;

function useSelect() {
  const [params] = useSearchParams();
  const { mobile } = useViewport();
  // Строка открывает документ в боковом окне без перехода; на телефоне — лист на весь экран.
  return (row: MemoApprovalRow) =>
    withParams(params, {
      memo: row.id,
      tab: "agree",
      panel: mobile ? null : "open",
      sheet: mobile ? "agree" : null,
    });
}

/** Статус строки словами: ждёт чьего шага («На согласовании · Директор») или итог маршрута. */
function RowStatus({ row }: { row: MemoApprovalRow }) {
  const { t } = useTranslation("approvals");
  if (row.status === "open") {
    return (
      <StatusTag tone="gold">
        {row.step_label ? t("list.waiting", { label: row.step_label }) : t("list.status.open")}
      </StatusTag>
    );
  }
  const tone = row.status === "approved" ? "green" : row.status === "rejected" ? "red" : "gold";
  return <StatusTag tone={tone}>{t(`list.status.${row.status}`)}</StatusTag>;
}

function Amount({ row }: { row: MemoApprovalRow }) {
  if (!row.amount) return <>—</>;
  return (
    <MoneyText
      value={row.amount.amount}
      {...(row.amount.currency === "UZS" ? {} : { currency: row.amount.currency })}
    />
  );
}

function Rows({ items, selected }: { items: readonly MemoApprovalRow[]; selected: string | null }) {
  const { t } = useTranslation("approvals");
  const { date } = useFormat();
  const { mobile } = useViewport();
  const select = useSelect();
  const navigate = useNavigate();
  const label = (row: MemoApprovalRow) => row.number ?? t(`kinds.${row.kind}`);
  const isSelected = (row: MemoApprovalRow) => selected === row.id;

  if (mobile) {
    return (
      <ul className="pf-dec-cards" aria-label={t("list.caption")}>
        {items.map((row) => (
          <li key={row.id} data-selected={isSelected(row)}>
            <div className="pf-dec-card-head">
              <Link
                className="pf-focusable pf-dec-number"
                to={select(row)}
                aria-label={t("list.select", { number: label(row) })}
              >
                {label(row)}
              </Link>
              <RowStatus row={row} />
            </div>
            <p className="pf-dec-card-subject">{row.subject}</p>
            <p className="pf-hint">
              {row.author?.full_name ?? "—"}
              {row.amount ? (
                <>
                  {" · "}
                  <Amount row={row} />
                </>
              ) : null}
            </p>
            <div className="pf-dec-card-foot">
              <span className="pf-hint">{date(row.created_at, "datetime")}</span>
              <LinkButton
                size="small"
                to={memoPath(row)}
                aria-label={t("list.openLabel", { number: label(row) })}
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
            <th scope="col">{t("list.columns.subject")}</th>
            <th scope="col">{t("list.columns.author")}</th>
            <th scope="col" className="pf-dec-right">
              {t("list.columns.amount")}
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
              data-selected={isSelected(row)}
              onClick={(event) => {
                if ((event.target as HTMLElement).closest("a,button")) return;
                void navigate(select(row), { replace: true });
              }}
            >
              <td className="pf-num">
                <Link
                  className="pf-focusable pf-dec-number"
                  to={select(row)}
                  replace
                  aria-label={t("list.select", { number: label(row) })}
                  aria-current={isSelected(row) ? "true" : undefined}
                >
                  {label(row)}
                </Link>
                <div className="pf-hint">{t(`kinds.${row.kind}`)}</div>
              </td>
              <td>{row.subject}</td>
              <td>{row.author?.full_name ?? "—"}</td>
              <td className="pf-dec-right">
                <Amount row={row} />
              </td>
              <td className="pf-num">{row.due_date ? date(row.due_date) : "—"}</td>
              <td className="pf-num">{date(row.created_at, "datetime")}</td>
              <td>
                <RowStatus row={row} />
              </td>
              <td>
                <LinkButton
                  size="small"
                  to={memoPath(row)}
                  aria-label={t("list.openLabel", { number: label(row) })}
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
 * EDS · На согласовании (SPEC-v3 §7.3): служебные записки, заявления и отчёты на шаге этого сотрудника («На моём шаге»)
 * или все, где он автор или участник маршрута; документ — в боковом окне «Согласование».
 */
export function MemoList() {
  const { t } = useTranslation(["approvals", "modules"]);
  const { me } = useAuth();
  const mayDecide = mayDecideMemos(me);
  const [params, setParams] = useSearchParams();
  const labels = useStateLabels();
  const scope = scopeOf(params.get("scope"), mayDecide ? "mine" : "all");
  const selected = params.get("memo");
  const title = t("modules:eds.sections.approvals");
  useDocumentTitle(title);

  const listParams = { scope, limit: PAGE };
  const query = useInfiniteQuery({
    queryKey: getListMemoApprovalsQueryKey(listParams),
    queryFn: ({ pageParam }) =>
      listMemoApprovals({ ...listParams, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = query.data?.pages.flatMap((page) => page.items) ?? [];

  const setScope = (value: Scope) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("scope", value);
        next.delete("memo");
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
          ? {
              title: t("approvals:state.notGranted.title"),
              text: t("approvals:state.notGranted.text"),
            }
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
        title={t(`approvals:list.empty.${scope}.title`)}
        text={t(`approvals:list.empty.${scope}.text`)}
        action={
          <Button
            onClick={() => {
              if (scope === "mine") setScope("all");
              else void query.refetch();
            }}
          >
            {t(`approvals:list.empty.${scope}.action`)}
          </Button>
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
              {t("approvals:list.more")}
            </Button>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="pf-dec-page">
      <PageHeader title={title} subtitle={t("approvals:list.subtitle")} />
      {mayDecide ? (
        <Segmented
          aria-label={t("approvals:list.scope.label")}
          value={scope}
          options={[
            { value: "mine", label: t("approvals:list.scope.mine") },
            { value: "all", label: t("approvals:list.scope.all") },
          ]}
          onChange={(value) => {
            setScope(value as Scope);
          }}
        />
      ) : null}
      <Card styles={{ body: { padding: 0 } }}>{body}</Card>
      {selected ? <AgreeSlot memoRef={selected} brief /> : null}
    </div>
  );
}
