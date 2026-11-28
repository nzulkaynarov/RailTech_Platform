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
import { DataBlock, ListSkeleton } from "../../../shared/ui/DataBlock";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { STATUS_FILTERS, letterPath, withParams } from "./api";
import { localName, useLetterDictionary } from "../dictionaries";
import { useStateLabels } from "./labels";
import { ResolutionSlot } from "./ResolutionPanel";
import { RowOpenLink } from "../../../shared/ui/RowOpenLink";
import { CompanyCell } from "../../../shared/ui/EntityCell";
import { NameCode } from "../../../shared/ui/NameCode";
import { PersonRefCell } from "../../PersonRefCell";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { TimeLeft } from "../../../shared/ui/TimeLeft";
import { PageFrame } from "../../../shared/ui/PageFrame";

const PAGE = 25;
/**
 * Ширины колонок по типу (platform-frontend.md §4.2): номер, тема (гибкая), корреспондент (заявка — второй строкой, как в
 * карточке на телефоне), исполнитель, срок, получено, статус, действие. На 1440 с открытым подменю таблица помещается в
 * рабочую область (1111 px) без прокрутки вбок (T1).
 */
const COLS = {
  number: 108,
  correspondent: 208,
  executor: 136,
  due: 104,
  received: 104,
  status: 168,
  // Стандарт интерфейса §7: вместо кнопки «Открыть» в каждой строке — стрелка перехода к письму.
  action: 56,
};
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
/** Под рукой — то, с чем работают каждый день; остальные статусы — в списке рядом. */
const MAIN_FILTERS: readonly Filter[] = ["awaiting_resolution", "on_control", "overdue", "all"];
const MORE_FILTERS = FILTERS.filter((value) => !MAIN_FILTERS.includes(value));

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
    <>
      {date(row.due)}
      <TimeLeft date={row.due} />
    </>
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
            {row.client_name ? (
              <p className="pf-letters-card-subject">
                <CompanyCell
                  name={row.client_name}
                  logoUrl={row.client_logo_url ?? null}
                  test={row.is_test}
                />
              </p>
            ) : null}
            {row.request_number ? <p className="pf-hint">{row.request_number}</p> : null}
            {row.executor ? <PersonRefCell person={row.executor} caption={null} /> : null}
            {row.due ? (
              <p className="pf-hint">
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
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<LetterRow>[] = [
    {
      id: "number",
      header: t("list.columns.number"),
      width: COLS.number,
      cellClassName: "pf-num",
      cell: (row) => (
        <Link
          className="pf-focusable pf-letters-number"
          to={select(row.number)}
          replace
          aria-label={t("list.select", { number: row.number })}
          aria-current={selected === row.number ? "true" : undefined}
        >
          {row.number}
        </Link>
      ),
    },
    {
      id: "subject",
      header: t("list.columns.subject"),
      width: null,
      cell: (row) => (
        <>
          {row.subject}
          {row.urgent ? (
            <>
              {" "}
              <StatusTag tone="red">{t("list.urgent")}</StatusTag>
            </>
          ) : null}
        </>
      ),
    },
    {
      id: "correspondent",
      header: t("list.columns.correspondent"),
      width: COLS.correspondent,
      cell: (row) => (
        <NameCode
          name={
            row.client_name ? (
              <CompanyCell
                name={row.client_name}
                logoUrl={row.client_logo_url ?? null}
                test={row.is_test}
              />
            ) : (
              "—"
            )
          }
          code={row.request_number}
          codeLabel={t("list.columns.request")}
        />
      ),
    },
    {
      id: "executor",
      header: t("list.columns.executor"),
      width: COLS.executor,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.executor?.name ?? undefined,
      cell: (row) => (row.executor ? <PersonRefCell person={row.executor} caption={null} /> : "—"),
    },
    {
      id: "due",
      header: t("list.columns.due"),
      width: COLS.due,
      cellClassName: "pf-num",
      cell: (row) => <Due row={row} />,
    },
    {
      id: "received",
      header: t("list.columns.received"),
      width: COLS.received,
      cellClassName: "pf-num",
      cell: (row) => date(row.received_at),
    },
    {
      id: "status",
      header: t("list.columns.status"),
      width: COLS.status,
      cell: (row) => <StatusTag kind="incoming" status={row.status} />,
    },
    {
      id: "action",
      header: t("list.columns.action"),
      headerHidden: true,
      width: COLS.action,
      cell: (row) => (
        <RowOpenLink
          to={letterPath(row.number)}
          label={t("list.openLabel", { number: row.number })}
          title={t("list.open")}
        />
      ),
    },
  ];
  return (
    <DataTable
      tableId="eds.inbox"
      caption={t("list.caption")}
      scrollLabel={t("list.scroll")}
      className="pf-letters-table"
      flexMin={224}
      columns={columns}
      rows={items}
      rowKey={(row) => row.id}
      rowAttrs={(row) => ({
        "data-selected": selected === row.number,
        onClick: (event) => {
          // Клик по строке — письмо в боковом окне; ссылки и кнопки внутри работают сами.
          if ((event.target as HTMLElement).closest("a,button")) return;
          void navigate(select(row.number), { replace: true });
        },
      })}
    />
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
    <PageFrame layout="registry">
      <div className="pf-letters">
        <PageHeader
          title={title}
          extra={
            canRegister ? (
              <LinkButton type="primary" to="/eds/register">
                {t("letters:register.action")}
              </LinkButton>
            ) : undefined
          }
        />
        <FilterBar tools>
          <Segmented
            aria-label={t("letters:list.filter.label")}
            value={filter}
            options={MAIN_FILTERS.map((value) => ({ value, label: filterLabel(value, t) }))}
            onChange={(value) => {
              setFilter(value);
            }}
          />
          <FilterField id="pf-letters-status" label={t("letters:list.filter.more")} width={240}>
            <Select
              id="pf-letters-status"
              allowClear
              value={MORE_FILTERS.includes(filter) ? filter : undefined}
              placeholder={t("letters:list.filter.more")}
              options={MORE_FILTERS.map((value) => ({ value, label: filterLabel(value, t) }))}
              onChange={(value: Filter | undefined) => {
                setFilter(value ?? "awaiting_resolution");
              }}
            />
          </FilterField>
          <FilterField id="pf-letters-kind" label={t("letters:listKind.label")} width={240}>
            <Select
              id="pf-letters-kind"
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
          </FilterField>
        </FilterBar>
        <Card styles={{ body: { padding: 0 } }}>
          <DataBlock busy={query.isPlaceholderData} resetKey={shownKey}>
            {body}
          </DataBlock>
        </Card>
        {selected ? <ResolutionSlot letterRef={selected} brief /> : null}
      </div>
    </PageFrame>
  );
}
