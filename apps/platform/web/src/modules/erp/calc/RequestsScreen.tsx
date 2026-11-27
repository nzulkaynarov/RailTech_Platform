import { keepPreviousData } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Pagination, Segmented } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import type { CalcRequestRow } from "../../../shared/api/generated/model";
import { useListCalcRequests } from "../../../shared/api/generated/platform-bff";
import { COMPANY_TIME_ZONE } from "../../../shared/lib/format";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useShownKey } from "../../../shared/lib/useShownKey";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { DataBlock } from "../../../shared/ui/DataBlock";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { TestTag } from "../../../shared/ui/TestTag";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  draftContinuePath,
  listRequestDrafts,
  type ListedDraft,
  restoreRequestDraft,
  clearRequestDraft,
} from "../../crm/request/draft";
import { calcPath, copyPath, isOverdue, useStateLabels } from "./api";
import { TaskSlot } from "./TaskPanel";
import { VisaIndicators } from "./VisaIndicators";

import "./calc.css";
import { RowOpenLink } from "../../../shared/ui/RowOpenLink";
import { TimeLeft } from "../../../shared/ui/TimeLeft";
import { useNotify } from "../../../shared/notify/NotifyProvider";

/**
 * Ширины колонок: номер, клиент и тема (гибкая), этап, срок, визы, ответственный, действие (UX-1c, S9). Ширина — по типу колонки (platform-frontend.md §4.2), на 1440 с открытым подменю — без прокрутки вбок (T1).
 */
const COLS = {
  number: 128,
  stage: 164,
  due: 120,
  visas: 180,
  responsible: 136,
  action: 156,
};

function companyToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: COMPANY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function Due({ due, closed = false }: { due: string; closed?: boolean }) {
  const { t } = useTranslation("calc");
  const { date } = useFormat();
  if (closed) return <span className="pf-num">{date(due)}</span>;
  return (
    <span className="pf-calc-due">
      <span className="pf-num">{date(due)}</span>
      {isOverdue(due, companyToday()) ? (
        <StatusTag tone="red">{t("list.overdue")}</StatusTag>
      ) : (
        <TimeLeft date={due} />
      )}
    </span>
  );
}

/** Заявка вне расчёта: КП ушло клиенту, стала проектом или закрыта — открывается только на просмотр. */
function isClosedRow(row: CalcRequestRow): boolean {
  return !["REQUEST", "RESOLUTION", "CALCULATION"].includes(row.step);
}

function Stage({ row }: { row: CalcRequestRow }) {
  const { t } = useTranslation(["calc", "dictionary"]);
  if (isClosedRow(row)) {
    return (
      <span className="pf-calc-stage">
        {row.step === "LOST" ? (
          <StatusTag tone="default">{t(`calc:list.outcome.${row.step}`)}</StatusTag>
        ) : (
          <StatusTag tone="green">{t(`calc:list.outcome.${row.step}`)}</StatusTag>
        )}
      </span>
    );
  }
  return (
    <span className="pf-calc-stage">
      <span>{t(`dictionary:stage.${row.step}`)}</span>
      <span className="pf-hint">{t(`calc:state.${row.state}`)}</span>
    </span>
  );
}

function selectHref(params: URLSearchParams, number: string): string {
  // План 1.1, «Создать → Расчёт»: выбор заявки открывает расчёт сразу с разбором файла
  if (params.get("new") === "calc") return `${calcPath(number)}?parse=1`;
  const next = new URLSearchParams(params);
  next.set("request", number);
  next.set("panel", "open");
  next.set("tab", "task");
  return `?${next.toString()}`;
}

function openPath(params: URLSearchParams, number: string): string {
  return params.get("new") === "calc" ? `${calcPath(number)}?parse=1` : calcPath(number);
}

function CopyLink({ row }: { row: CalcRequestRow }) {
  const { t } = useTranslation("calc");
  const { mobile } = useViewport();
  const { me } = useAuth();
  // Новую заявку создаёт тот, у кого «Контрагенты» на запись: остальным кнопка — тупик (403 при создании)
  if (!canEdit(me, "crm.clients")) return null;
  return (
    <LinkButton
      size="small"
      to={copyPath(row.number, row.crm_client_id, mobile)}
      aria-label={t("list.copyLabel", { number: row.number })}
    >
      {t("list.copy")}
    </LinkButton>
  );
}

function Rows({ items, selected }: { items: readonly CalcRequestRow[]; selected: string | null }) {
  const { t } = useTranslation("calc");
  const { mobile } = useViewport();
  const [params] = useSearchParams();
  const navigate = useNavigate();

  if (mobile) {
    return (
      <ul className="pf-calc-cards" aria-label={t("list.caption")}>
        {items.map((row) => (
          <li key={row.number}>
            <div className="pf-calc-card-head">
              <Link className="pf-focusable pf-calc-number" to={openPath(params, row.number)}>
                {row.number}
              </Link>
              <Due due={row.due} closed={isClosedRow(row)} />
            </div>
            <p className="pf-calc-card-title">
              {row.client ?? row.title} <TestTag value={row.is_test} />
            </p>
            <p className="pf-hint">
              <Stage row={row} />
            </p>
            <VisaIndicators visas={row.visas} />
            <div className="pf-calc-card-foot">
              <span className="pf-hint">{row.responsible ?? "—"}</span>
              <span className="pf-calc-row">
                {isClosedRow(row) ? <CopyLink row={row} /> : null}
                <LinkButton
                  size="small"
                  to={openPath(params, row.number)}
                  aria-label={t("list.openLabel", { number: row.number })}
                >
                  {t("list.open")}
                </LinkButton>
              </span>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<CalcRequestRow>[] = [
    {
      id: "number",
      header: t("list.columns.number"),
      width: COLS.number,
      cellClassName: "pf-num",
      cell: (row) => (
        <>
          <Link
            className="pf-focusable pf-calc-number"
            to={isClosedRow(row) ? openPath(params, row.number) : selectHref(params, row.number)}
            replace={params.get("new") !== "calc" && !isClosedRow(row)}
            aria-label={t("list.select", { number: row.number })}
            aria-current={selected === row.number ? "true" : undefined}
          >
            {row.number}
          </Link>
        </>
      ),
    },
    {
      id: "client",
      header: t("list.columns.client"),
      width: null,
      cell: (row) => (
        <>
          <div>
            {row.client ?? "—"} <TestTag value={row.is_test} />
          </div>
          <div className="pf-hint">{row.title}</div>
        </>
      ),
    },
    {
      id: "stage",
      header: t("list.columns.stage"),
      width: COLS.stage,
      cell: (row) => (
        <>
          <Stage row={row} />
        </>
      ),
    },
    {
      id: "due",
      header: t("list.columns.due"),
      width: COLS.due,
      cell: (row) => (
        <>
          <Due due={row.due} closed={isClosedRow(row)} />
        </>
      ),
    },
    {
      id: "visas",
      header: t("list.columns.visas"),
      width: COLS.visas,
      cell: (row) => (
        <>
          <VisaIndicators visas={row.visas} />
        </>
      ),
    },
    {
      id: "responsible",
      header: t("list.columns.responsible"),
      width: COLS.responsible,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.responsible ?? undefined,
      cell: (row) => row.responsible ?? "—",
    },
    {
      id: "action",
      header: t("list.columns.action"),
      headerHidden: true,
      width: COLS.action,
      cell: (row) => (
        <span className="pf-calc-row">
          {isClosedRow(row) ? <CopyLink row={row} /> : null}
          <RowOpenLink
            to={openPath(params, row.number)}
            label={t("list.openLabel", { number: row.number })}
            title={t("list.open")}
          />
        </span>
      ),
    },
  ];
  return (
    <DataTable
      tableId="erp.requests"
      caption={t("list.caption")}
      scrollLabel={t("list.scroll")}
      className="pf-calc-table"
      flexMin={220}
      columns={columns}
      rows={items}
      rowKey={(row) => row.number}
      rowAttrs={(row) => ({
        "data-selected": selected === row.number,
        onClick: (event) => {
          // Клик по строке — задание в боковом окне без перехода; ссылки и кнопки работают сами.
          if ((event.target as HTMLElement).closest("a,button")) return;
          if (isClosedRow(row)) {
            void navigate(openPath(params, row.number));
            return;
          }
          void navigate(selectHref(params, row.number), { replace: true });
        },
      })}
    />
  );
}

type Tab = "open" | "drafts" | "closed" | "all";
const TABS: readonly Tab[] = ["open", "drafts", "closed", "all"];
const PAGE_SIZE = 25;

function tabOf(value: string | null): Tab {
  return TABS.find((tab) => tab === value) ?? "open";
}

function draftName(item: ListedDraft, fallback: string): string {
  const { state } = item.draft;
  return state.company?.name ?? state.clientName ?? (state.summary.trim().slice(0, 40) || fallback);
}

/** Вкладка «Черновики»: начатое и не отправленное в этой вкладке браузера. «Продолжить» открывает форму с тем, что введено. */
function Drafts() {
  const { t } = useTranslation("calc");
  const { me } = useAuth();
  const notify = useNotify();
  const { date } = useFormat();
  const { mobile } = useViewport();
  const userId = me.id;
  const [version, setVersion] = useState(0);
  // `version` меняется при удалении и возврате — список перечитывается из хранилища вкладки
  const rows = userId ? (version >= 0 ? listRequestDrafts(userId) : []) : [];
  const columns: DataColumn<ListedDraft>[] = [
    {
      id: "client",
      header: t("list.drafts.client"),
      width: 240,
      cell: (item) =>
        item.draft.state.company?.name ?? item.draft.state.clientName ?? t("list.drafts.noClient"),
    },
    {
      id: "text",
      header: t("list.drafts.text"),
      width: null,
      cellClassName: "pf-ell",
      cell: (item) => item.draft.state.summary.trim() || t("list.drafts.noText"),
    },
    {
      id: "saved",
      header: t("list.drafts.saved"),
      width: 168,
      cellClassName: "pf-num",
      cell: (item) => date(item.draft.savedAt, "datetime"),
    },
    {
      id: "action",
      header: t("list.columns.action"),
      headerHidden: true,
      width: 240,
      cell: (item) => {
        const name = draftName(item, t("list.drafts.noClient"));
        return (
          <span className="pf-calc-row">
            <LinkButton
              size="small"
              to={draftContinuePath(item.scope, mobile)}
              aria-label={t("list.drafts.continueLabel", { name })}
            >
              {t("list.drafts.continue")}
            </LinkButton>
            <Button
              size="small"
              type="text"
              aria-label={t("list.drafts.removeLabel", { name })}
              onClick={() => {
                if (!userId) return;
                clearRequestDraft(userId, item.scope);
                setVersion((v) => v + 1);
                const key = `draft-${item.scope}`;
                notify.push({
                  key,
                  title: t("list.drafts.removed"),
                  duration: 6,
                  action: {
                    label: t("list.drafts.undo"),
                    onClick: () => {
                      restoreRequestDraft(userId, item.scope, item.draft);
                      setVersion((v) => v + 1);
                    },
                  },
                });
              }}
            >
              {t("list.drafts.remove")}
            </Button>
          </span>
        );
      },
    },
  ];
  if (rows.length === 0) {
    return (
      <EmptyState
        title={t("list.drafts.emptyTitle")}
        text={t("list.drafts.emptyText")}
        action={
          canEdit(me, "crm.clients") ? (
            <LinkButton
              to={mobile ? "/crm/clients?create=1" : "/crm/clients?create=1&panel=open&tab=card"}
            >
              {t("list.drafts.emptyAction")}
            </LinkButton>
          ) : undefined
        }
      />
    );
  }
  return (
    <DataTable
      tableId="erp.requests.drafts"
      caption={t("list.drafts.caption")}
      scrollLabel={t("list.drafts.scroll")}
      flexMin={220}
      columns={columns}
      rows={rows}
      rowKey={(item) => item.scope}
    />
  );
}

/**
 * Расчёт · реестр заявок (SPEC-v3 §7.4 «Все запросы», ЗАЯВ-1): вкладки «В работе · Черновики · Закрытые · Все», «Все / Мои»,
 * поиск по номеру, клиенту и тексту, страницы; в шапке — сколько заявок. Закрытая и прошлая заявка открывается на
 * просмотр, «По образцу» заводит новую с сутью и файлом прежней. Клик по строке в работе — «Задание» в боковом окне.
 */
export function RequestsScreen() {
  const { t } = useTranslation(["calc", "modules"]);
  const ids = useId();
  const [params, setParams] = useSearchParams();
  const mine = params.get("mine") === "1";
  const tab = tabOf(params.get("list"));
  const q = (params.get("q") ?? "").trim();
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const labels = useStateLabels();
  const title = t("modules:erp.sections.requests");
  useDocumentTitle(title);
  const state = tab === "drafts" ? "open" : tab;
  const query = useListCalcRequests(
    {
      state,
      ...(mine ? { mine: true } : {}),
      ...(q ? { q } : {}),
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    },
    { query: { enabled: tab !== "drafts", placeholderData: keepPreviousData } },
  );
  const shownKey = useShownKey(query.queryKey, query.isPlaceholderData);
  const selected = params.get("request");
  const { me } = useAuth();
  const draftCount = me.id ? listRequestDrafts(me.id).length : 0;
  const total = tab === "drafts" ? draftCount : (query.data?.total ?? query.data?.items.length);

  const change = (changes: Record<string, string | null>) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        if (!("page" in changes)) next.delete("page");
        return next;
      },
      { replace: true },
    );
  };
  const filtered = q !== "" || mine;

  return (
    <div className="pf-calc">
      <PageHeader
        title={title}
        subtitle={total === undefined ? undefined : t("calc:list.total", { count: total })}
      />
      <FilterBar label={t("calc:list.filters")} tools={tab !== "drafts"}>
        <Segmented
          aria-label={t("calc:list.tabs.label")}
          value={tab}
          options={TABS.map((value) => ({ value, label: t(`calc:list.tabs.${value}`) }))}
          onChange={(value) => {
            change({ list: value === "open" ? null : value });
          }}
        />
        {tab === "drafts" ? null : (
          <>
            <Segmented
              aria-label={t("calc:list.scope.label")}
              value={mine ? "mine" : "all"}
              options={[
                { value: "all", label: t("calc:list.scope.all") },
                { value: "mine", label: t("calc:list.scope.mine") },
              ]}
              onChange={(value) => {
                change({ mine: value === "mine" ? "1" : null });
              }}
            />
            <FilterField id={`${ids}-q`} label={t("calc:list.search.label")} grow>
              <Input.Search
                id={`${ids}-q`}
                key={q}
                defaultValue={q}
                allowClear
                placeholder={t("calc:list.search.placeholder")}
                onSearch={(value) => {
                  change({ q: value.trim() || null });
                }}
              />
            </FilterField>
          </>
        )}
      </FilterBar>
      {params.get("new") === "calc" ? (
        <Alert type="info" showIcon message={t("calc:list.pickForCalc")} />
      ) : null}
      <Card styles={{ body: { padding: 0 } }}>
        {tab === "drafts" ? (
          <Drafts />
        ) : (
          <DataBlock busy={query.isPlaceholderData} resetKey={shownKey}>
            <QueryState query={query} labels={labels} rows={10}>
              {(data) =>
                data.items.length === 0 ? (
                  mine && q === "" && tab === "open" ? (
                    <EmptyState
                      title={t("calc:list.empty.mineTitle")}
                      text={t("calc:list.empty.mineText")}
                      action={
                        <LinkButton
                          to={
                            params.get("new") === "calc"
                              ? "/erp/requests?new=calc"
                              : "/erp/requests"
                          }
                        >
                          {t("calc:list.empty.mineAction")}
                        </LinkButton>
                      }
                    />
                  ) : (
                    <EmptyState
                      title={t(
                        filtered
                          ? "calc:list.empty.filteredTitle"
                          : tab === "closed"
                            ? "calc:list.empty.closedTitle"
                            : tab === "all"
                              ? "calc:list.empty.allTitle"
                              : "calc:list.empty.title",
                      )}
                      text={t(
                        filtered
                          ? "calc:list.empty.filteredText"
                          : tab === "closed"
                            ? "calc:list.empty.closedText"
                            : tab === "all"
                              ? "calc:list.empty.allText"
                              : "calc:list.empty.text",
                      )}
                      action={
                        filtered ? (
                          <Button
                            onClick={() => {
                              change({ q: null, mine: null });
                            }}
                          >
                            {t("calc:list.empty.filteredAction")}
                          </Button>
                        ) : tab === "open" ? (
                          <Button
                            onClick={() => {
                              void query.refetch();
                            }}
                          >
                            {t("calc:list.empty.action")}
                          </Button>
                        ) : undefined
                      }
                    />
                  )
                ) : (
                  <>
                    <Rows items={data.items} selected={selected} />
                    {(data.total ?? data.items.length) > PAGE_SIZE ? (
                      <div className="pf-calc-pager">
                        <Pagination
                          current={page}
                          pageSize={PAGE_SIZE}
                          total={data.total ?? data.items.length}
                          showSizeChanger={false}
                          size="small"
                          aria-label={t("calc:list.pager")}
                          onChange={(next) => {
                            change({ page: next === 1 ? null : String(next) });
                          }}
                        />
                      </div>
                    ) : null}
                  </>
                )
              }
            </QueryState>
          </DataBlock>
        )}
      </Card>
      {selected && tab !== "drafts" ? <TaskSlot number={selected} brief /> : null}
    </div>
  );
}
