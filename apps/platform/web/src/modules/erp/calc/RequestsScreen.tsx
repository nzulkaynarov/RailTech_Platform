import { Button, Card, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { CalcRequestRow } from "../../../shared/api/generated/model";
import { useListCalcRequests } from "../../../shared/api/generated/platform-bff";
import { COMPANY_TIME_ZONE } from "../../../shared/lib/format";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { calcPath, isOverdue, useStateLabels } from "./api";
import { TaskSlot } from "./TaskPanel";
import { VisaIndicators } from "./VisaIndicators";

import "./calc.css";

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

function Due({ due }: { due: string }) {
  const { t } = useTranslation("calc");
  const { date } = useFormat();
  return (
    <span className="pf-calc-due">
      <span className="pf-num">{date(due)}</span>
      {isOverdue(due, companyToday()) ? (
        <StatusTag tone="red">{t("list.overdue")}</StatusTag>
      ) : null}
    </span>
  );
}

function Stage({ row }: { row: CalcRequestRow }) {
  const { t } = useTranslation(["calc", "dictionary"]);
  return (
    <span className="pf-calc-stage">
      <span>{t(`dictionary:stage.${row.step}`)}</span>
      <span className="pf-hint">{t(`calc:state.${row.state}`)}</span>
    </span>
  );
}

function selectHref(params: URLSearchParams, number: string): string {
  const next = new URLSearchParams(params);
  next.set("request", number);
  next.set("panel", "open");
  next.set("tab", "task");
  return `?${next.toString()}`;
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
              <Link className="pf-focusable pf-calc-number" to={calcPath(row.number)}>
                {row.number}
              </Link>
              <Due due={row.due} />
            </div>
            <p className="pf-calc-card-title">{row.client ?? row.title}</p>
            <p className="pf-hint">
              <Stage row={row} />
            </p>
            <VisaIndicators visas={row.visas} />
            <div className="pf-calc-card-foot">
              <span className="pf-hint">{row.responsible ?? "—"}</span>
              <LinkButton
                size="small"
                to={calcPath(row.number)}
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
            to={selectHref(params, row.number)}
            replace
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
          <div>{row.client ?? "—"}</div>
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
          <Due due={row.due} />
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
        <>
          <LinkButton
            size="small"
            to={calcPath(row.number)}
            aria-label={t("list.openLabel", { number: row.number })}
          >
            {t("list.open")}
          </LinkButton>
        </>
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
          void navigate(selectHref(params, row.number), { replace: true });
        },
      })}
    />
  );
}

/**
 * Расчёт · «Заявки в расчёте» и «Мои расчёты» (SPEC-v3 §7.4 «Все запросы»): ЗВ-номер · клиент · стадия · срок расчёта · три
 * индикатора виз · ответственный · «Открыть расчёт». Клик по строке — «Задание» в боковом окне без перехода.
 */
export function RequestsScreen() {
  const { t } = useTranslation(["calc", "modules"]);
  const [params, setParams] = useSearchParams();
  const mine = params.get("mine") === "1";
  const labels = useStateLabels();
  const title = t("modules:erp.sections.requests");
  useDocumentTitle(title);
  const query = useListCalcRequests(mine ? { mine: true } : undefined);
  const selected = params.get("request");

  return (
    <div className="pf-calc">
      <PageHeader title={title} subtitle={t("calc:list.subtitle")} />
      <Segmented
        aria-label={t("calc:list.scope.label")}
        value={mine ? "mine" : "all"}
        options={[
          { value: "all", label: t("calc:list.scope.all") },
          { value: "mine", label: t("calc:list.scope.mine") },
        ]}
        onChange={(value) => {
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              if (value === "mine") next.set("mine", "1");
              else next.delete("mine");
              return next;
            },
            { replace: true },
          );
        }}
      />
      <Card styles={{ body: { padding: 0 } }}>
        <QueryState query={query} labels={labels} rows={10}>
          {(data) =>
            data.items.length === 0 ? (
              <EmptyState
                title={t(mine ? "calc:list.empty.mineTitle" : "calc:list.empty.title")}
                text={t(mine ? "calc:list.empty.mineText" : "calc:list.empty.text")}
                action={
                  mine ? (
                    <LinkButton to="/erp/requests">{t("calc:list.empty.mineAction")}</LinkButton>
                  ) : (
                    <Button
                      onClick={() => {
                        void query.refetch();
                      }}
                    >
                      {t("calc:list.empty.action")}
                    </Button>
                  )
                }
              />
            ) : (
              <Rows items={data.items} selected={selected} />
            )
          }
        </QueryState>
      </Card>
      {selected ? <TaskSlot number={selected} brief /> : null}
    </div>
  );
}
