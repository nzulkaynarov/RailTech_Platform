import { Button, Card, Segmented, Select } from "antd";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type {
  LetterRow,
  LetterStatus,
  ListLettersParams,
} from "../../../shared/api/generated/model";
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
import { localName, useLetterDictionary } from "../dictionaries";
import { useStateLabels } from "./labels";
import { ResolutionSlot } from "./ResolutionPanel";

const PAGE = 25;
/**
 * Ширины колонок по типу (platform-frontend.md §4.2): номер, тема (гибкая), корреспондент (заявка — второй строкой, как в
 * карточке на телефоне), исполнитель, срок, получено, статус, действие. На 1440 с открытым подменю таблица помещается в
 * рабочую область (1111 px) без прокрутки вбок (T1).
 */
const COLS = [108, null, 160, 136, 104, 104, 168, 104] as const;
/** Фильтры журнала (P8b, SPEC-v3 §3.2a п. 6): «На контроле» и «Просрочено» — признаки EDS, не статусы. */
type Flag = "on_control" | "overdue";
type Filter = LetterStatus | Flag | "all";
/** Порядок фильтров: что ждёт решения и контроля — первым (делопроизводитель и директор), затем остальные статусы. */
const FILTERS: readonly Filter[] = [
  "awaiting_resolution",
  "on_control",
  "overdue",
  "executed",
  "noted",
  ...STATUS_FILTERS.filter((s) => s !== "awaiting_resolution"),
  "all",
];

function filterOf(value: string | null): Filter {
  return FILTERS.find((s) => s === value) ?? "awaiting_resolution";
}

function paramsOf(filter: Filter): ListLettersParams {
  if (filter === "all") return {};
  if (filter === "on_control") return { on_control: true };
  if (filter === "overdue") return { overdue: true };
  return { status: [filter] };
}

function filterLabel(filter: Filter, t: (key: string) => string): string {
  if (filter === "all") return t("letters:list.filter.all");
  if (filter === "on_control" || filter === "overdue") return t(`letters:list.filter.${filter}`);
  return t(`dictionary:status.incoming.${filter}`);
}

/** Срок по резолюции: просрочка — красным и словом (признак EDS `overdue`). */
function Due({ row }: { row: LetterRow }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  if (!row.due) return <>—</>;
  return row.overdue ? (
    <span className="pf-letters-due--overdue">{t("list.dueOverdue", { date: date(row.due) })}</span>
  ) : (
    <>{date(row.due)}</>
  );
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
            {row.executor || row.due ? (
              <p className="pf-hint">
                {row.executor ? `${row.executor.name} · ` : ""}
                <Due row={row} />
              </p>
            ) : null}
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
        style={{ minWidth: tableMinWidth(COLS, 224) }}
      >
        <caption className="pf-sr-only">{t("list.caption")}</caption>
        <TableCols widths={COLS} />
        <thead>
          <tr>
            <th scope="col">{t("list.columns.number")}</th>
            <th scope="col">{t("list.columns.subject")}</th>
            <th scope="col">{t("list.columns.correspondent")}</th>
            <th scope="col">{t("list.columns.executor")}</th>
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
              <td>
                <div className="pf-ell" title={row.client_name ?? undefined}>
                  {row.client_name ?? "—"}
                </div>
                {row.request_number ? (
                  <div className="pf-hint pf-num pf-ell">
                    <span className="pf-sr-only">{t("list.columns.request")}: </span>
                    {row.request_number}
                  </div>
                ) : null}
              </td>
              <td className="pf-ell" title={row.executor?.name ?? undefined}>
                {row.executor?.name ?? "—"}
              </td>
              <td className="pf-num">
                <Due row={row} />
              </td>
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
  const { t, i18n } = useTranslation(["letters", "modules", "dictionary"]);
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const labels = useStateLabels();
  const canRegister = canEdit(me, "eds.inbox.register");
  const filter = filterOf(params.get("status"));
  const kind = params.get("kind") || null;
  const selected = params.get("letter");
  const title = t("modules:eds.sections.inbox");
  useDocumentTitle(title);
  // Вид документа — справочник (EDS-REG), со скрытыми: старые письма тоже находятся.
  const kinds = useLetterDictionary("letter-kinds", true);

  const listParams: ListLettersParams = {
    ...paramsOf(filter),
    ...(kind ? { kind } : {}),
    limit: PAGE,
  };
  const query = useInfiniteQuery({
    queryKey: getListLettersQueryKey(listParams),
    queryFn: ({ pageParam }) =>
      listLetters({ ...listParams, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = query.data?.pages.flatMap((page) => page.items) ?? [];

  const setKind = (value: string | undefined) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set("kind", value);
        else next.delete("kind");
        next.delete("letter");
        next.delete("sheet");
        return next;
      },
      { replace: true },
    );
  };

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
      <PageHeader
        title={title}
        subtitle={t("letters:list.subtitle")}
        extra={
          canRegister ? (
            <LinkButton type="primary" to="/eds/register">
              {t("letters:register.action")}
            </LinkButton>
          ) : undefined
        }
      />
      {/* На узком экране фильтр прокручивается вбок, обрезанный край виден — все варианты доступны (UX-2b) */}
      <div className="pf-letters-filters">
        <div className="pf-letters-filter">
          <Segmented
            aria-label={t("letters:list.filter.label")}
            value={filter}
            options={FILTERS.map((value) => ({ value, label: filterLabel(value, t) }))}
            onChange={(value) => {
              setFilter(value);
            }}
          />
        </div>
        <label htmlFor="pf-letters-kind" className="pf-sr-only">
          {t("letters:listKind.label")}
        </label>
        <Select
          id="pf-letters-kind"
          className="pf-letters-kind"
          allowClear
          value={kind ?? undefined}
          placeholder={t("letters:listKind.all")}
          loading={kinds.isPending}
          options={(kinds.data?.items ?? []).map((item) => ({
            value: item.code,
            label: localName(item.name, i18n.language),
          }))}
          onChange={(value: string | undefined) => {
            setKind(value);
          }}
        />
      </div>
      <Card styles={{ body: { padding: 0 } }}>
        <DataBlock busy={query.isPlaceholderData} resetKey={shownKey}>
          {body}
        </DataBlock>
      </Card>
      {selected ? <ResolutionSlot letterRef={selected} brief /> : null}
    </div>
  );
}
