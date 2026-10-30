import { Button, Card, Segmented } from "antd";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { LetterRow, LetterStatus } from "../../../shared/api/generated/model";
import { getListLettersQueryKey, listLetters } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { useShownKey } from "../../../shared/lib/useShownKey";
import { DataBlock, ListSkeleton, TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { STATUS_FILTERS, letterPath, withParams } from "./api";
import { useStateLabels } from "./labels";
import { ResolutionSlot } from "./ResolutionPanel";

const PAGE = 25;
/** Ширины колонок: номер, тема (гибкая), клиент, заявка, получено, статус, действие (UX-1c, S9) */
const COLS = [120, null, 180, 120, 110, 170, 110] as const;
type Filter = LetterStatus | "all";

function filterOf(value: string | null): Filter {
  if (value === "all") return "all";
  return STATUS_FILTERS.find((s) => s === value) ?? "awaiting_resolution";
}

function useSelect() {
  const [params] = useSearchParams();
  const { mobile } = useViewport();
  // Строка открывает письмо в боковом окне без перехода; на телефоне — лист на весь экран.
  return (number: string) =>
    withParams(params, {
      letter: number,
      tab: "resolution",
      panel: mobile ? null : "open",
      sheet: mobile ? "resolution" : null,
    });
}

function Rows({ items, selected }: { items: readonly LetterRow[]; selected: string | null }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { mobile } = useViewport();
  const select = useSelect();
  const navigate = useNavigate();

  if (mobile) {
    return (
      <ul className="pf-letters-cards" aria-label={t("list.caption")}>
        {items.map((row) => (
          <li key={row.id} data-selected={selected === row.number}>
            <div className="pf-letters-card-head">
              <Link
                className="pf-focusable pf-letters-number"
                to={select(row.number)}
                aria-label={t("list.select", { number: row.number })}
              >
                {row.number}
              </Link>
              <StatusTag kind="incoming" status={row.status} />
            </div>
            <p className="pf-letters-card-subject">{row.subject}</p>
            <p className="pf-hint">
              {[row.client_name, row.request_number].filter(Boolean).join(" · ")}
            </p>
            <div className="pf-letters-card-foot">
              <span className="pf-hint">
                {date(row.received_at)}
                {row.urgent ? ` · ${t("list.urgent")}` : ""}
              </span>
              <LinkButton
                size="small"
                to={letterPath(row.number)}
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
      <table
        className="pf-letters-table pf-fixed-table"
        style={{ minWidth: tableMinWidth(COLS, 240) }}
      >
        <caption className="pf-sr-only">{t("list.caption")}</caption>
        <TableCols widths={COLS} />
        <thead>
          <tr>
            <th scope="col">{t("list.columns.number")}</th>
            <th scope="col">{t("list.columns.subject")}</th>
            <th scope="col">{t("list.columns.client")}</th>
            <th scope="col">{t("list.columns.request")}</th>
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
              data-selected={selected === row.number}
              onClick={(event) => {
                // Клик по строке — письмо в боковом окне; ссылки и кнопки внутри работают сами.
                if ((event.target as HTMLElement).closest("a,button")) return;
                void navigate(select(row.number), { replace: true });
              }}
            >
              <td className="pf-num">
                <Link
                  className="pf-focusable pf-letters-number"
                  to={select(row.number)}
                  replace
                  aria-label={t("list.select", { number: row.number })}
                  aria-current={selected === row.number ? "true" : undefined}
                >
                  {row.number}
                </Link>
              </td>
              <td>
                {row.subject}
                {row.urgent ? (
                  <>
                    {" "}
                    <StatusTag tone="red">{t("list.urgent")}</StatusTag>
                  </>
                ) : null}
              </td>
              <td className="pf-ell" title={row.client_name ?? undefined}>
                {row.client_name ?? "—"}
              </td>
              <td className="pf-num">{row.request_number ?? "—"}</td>
              <td className="pf-num">{date(row.received_at)}</td>
              <td>
                <StatusTag kind="incoming" status={row.status} />
              </td>
              <td>
                <LinkButton
                  size="small"
                  to={letterPath(row.number)}
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

/** EDS · Входящие письма (SPEC-v3 §7.3): список со статусом словами, фильтр (по умолчанию «Ждёт резолюции»), письмо — в боковом окне. */
export function InboxList() {
  const { t } = useTranslation(["letters", "modules", "dictionary"]);
  const [params, setParams] = useSearchParams();
  const labels = useStateLabels();
  const filter = filterOf(params.get("status"));
  const selected = params.get("letter");
  const title = t("modules:eds.sections.inbox");
  useDocumentTitle(title);

  const listParams = { ...(filter === "all" ? {} : { status: [filter] }), limit: PAGE };
  const query = useInfiniteQuery({
    queryKey: getListLettersQueryKey(listParams),
    queryFn: ({ pageParam }) =>
      listLetters({ ...listParams, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = query.data?.pages.flatMap((page) => page.items) ?? [];

  const setFilter = (value: Filter) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value === "awaiting_resolution") next.delete("status");
        else next.set("status", value);
        next.delete("letter");
        next.delete("sheet");
        return next;
      },
      { replace: true },
    );
  };

  const shownKey = useShownKey(getListLettersQueryKey(listParams), query.isPlaceholderData);
  let body;
  if (query.isPending) {
    body = <ListSkeleton rows={PAGE} />;
  } else if (query.isError) {
    const error = query.error;
    const text =
      error instanceof ApiError && error.status === 403
        ? error.details["reason"] === "eds_not_granted"
          ? { title: t("letters:state.notGranted.title"), text: t("letters:state.notGranted.text") }
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
    const kind = filter === "awaiting_resolution" ? "awaiting" : filter === "all" ? "all" : "other";
    body = (
      <EmptyState
        title={t(`letters:list.empty.${kind}.title`)}
        text={t(`letters:list.empty.${kind}.text`)}
        action={
          <Button
            onClick={() => {
              if (kind === "all") void query.refetch();
              else setFilter("all");
            }}
          >
            {t(`letters:list.empty.${kind}.action`)}
          </Button>
        }
      />
    );
  } else {
    body = (
      <>
        <Rows items={rows} selected={selected} />
        {query.hasNextPage ? (
          <div className="pf-letters-pager">
            <Button
              loading={query.isFetchingNextPage}
              onClick={() => {
                void query.fetchNextPage();
              }}
            >
              {t("letters:list.more")}
            </Button>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="pf-letters">
      <PageHeader title={title} subtitle={t("letters:list.subtitle")} />
      <Segmented
        aria-label={t("letters:list.filter.label")}
        value={filter}
        options={[
          ...STATUS_FILTERS.map((value) => ({
            value,
            label: t(`dictionary:status.incoming.${value}`),
          })),
          { value: "all", label: t("letters:list.filter.all") },
        ]}
        onChange={(value) => {
          setFilter(value as Filter);
        }}
      />
      <Card styles={{ body: { padding: 0 } }}>
        <DataBlock busy={query.isPlaceholderData} resetKey={shownKey}>
          {body}
        </DataBlock>
      </Card>
      {selected ? <ResolutionSlot letterRef={selected} brief /> : null}
    </div>
  );
}
