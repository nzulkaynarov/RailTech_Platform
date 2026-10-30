import { Button, Card } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { CalcRequestRow } from "../../../shared/api/generated/model";
import { useListCalcRequests } from "../../../shared/api/generated/platform-bff";
import { COMPANY_TIME_ZONE } from "../../../shared/lib/format";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { calcPath, isOverdue, useStateLabels } from "./api";
import { TaskSlot } from "./TaskPanel";
import { VisaIndicators } from "./VisaIndicators";

import "./calc.css";

/** Ширины колонок: номер, клиент и тема (гибкая), этап, срок, визы, ответственный, действие (UX-1c, S9) */
const COLS = [140, null, 180, 110, 150, 160, 140] as const;

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
  return (
    <ScrollRegion label={t("list.scroll")}>
      <table
        className="pf-calc-table pf-fixed-table"
        style={{ minWidth: tableMinWidth(COLS, 220) }}
      >
        <caption className="pf-sr-only">{t("list.caption")}</caption>
        <TableCols widths={COLS} />
        <thead>
          <tr>
            <th scope="col">{t("list.columns.number")}</th>
            <th scope="col">{t("list.columns.client")}</th>
            <th scope="col">{t("list.columns.stage")}</th>
            <th scope="col">{t("list.columns.due")}</th>
            <th scope="col">{t("list.columns.visas")}</th>
            <th scope="col">{t("list.columns.responsible")}</th>
            <th scope="col">
              <span className="pf-sr-only">{t("list.columns.action")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr
              key={row.number}
              data-selected={selected === row.number}
              onClick={(event) => {
                // Клик по строке — задание в боковом окне без перехода; ссылки и кнопки работают сами.
                if ((event.target as HTMLElement).closest("a,button")) return;
                void navigate(selectHref(params, row.number), { replace: true });
              }}
            >
              <td className="pf-num">
                <Link
                  className="pf-focusable pf-calc-number"
                  to={selectHref(params, row.number)}
                  replace
                  aria-label={t("list.select", { number: row.number })}
                  aria-current={selected === row.number ? "true" : undefined}
                >
                  {row.number}
                </Link>
              </td>
              <td>
                <div>{row.client ?? "—"}</div>
                <div className="pf-hint">{row.title}</div>
              </td>
              <td>
                <Stage row={row} />
              </td>
              <td>
                <Due due={row.due} />
              </td>
              <td>
                <VisaIndicators visas={row.visas} />
              </td>
              <td className="pf-ell" title={row.responsible ?? undefined}>
                {row.responsible ?? "—"}
              </td>
              <td>
                <LinkButton
                  size="small"
                  to={calcPath(row.number)}
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
 * Расчёт · «Заявки в расчёте» и «Мои расчёты» (SPEC-v3 §7.4 «Все запросы»): ЗВ-номер · клиент · стадия · срок расчёта · три
 * индикатора виз · ответственный · «Открыть расчёт». Клик по строке — «Задание» в боковом окне без перехода.
 */
export function RequestsScreen({ mine }: { mine: boolean }) {
  const { t } = useTranslation(["calc", "modules"]);
  const [params] = useSearchParams();
  const labels = useStateLabels();
  const title = t(`modules:erp.sections.${mine ? "calc" : "requests"}`);
  useDocumentTitle(title);
  const query = useListCalcRequests(mine ? { mine: true } : undefined);
  const selected = params.get("request");

  return (
    <div className="pf-calc">
      <PageHeader
        title={title}
        subtitle={t(mine ? "calc:list.subtitleMine" : "calc:list.subtitle")}
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
