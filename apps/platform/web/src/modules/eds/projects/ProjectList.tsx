import { keepPreviousData } from "@tanstack/react-query";
import { Button, Card, Checkbox, Input, Pagination, Segmented, Select } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { ProjectRow, ProjectStage } from "../../../shared/api/generated/model";
import { useListEdsProjects } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { useShownKey } from "../../../shared/lib/useShownKey";
import { DataBlock, ListSkeleton, TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { PAGE_SIZE, type Scope, projectPath, scopeOf } from "./api";
import { useStateLabels } from "./labels";
import { ProjectStatusTag } from "./status";

import "../decision/decision.css";
import "./projects.css";

/** Ширины колонок: номер и сумма, клиент и название (гибкая), шаг, статус клиента, документы, срок, ответственный, действие (UX-1c, S9) */
const COLS = [140, null, 190, 140, 120, 100, 150, 110] as const;

const STEPS: readonly ProjectStage[] = ["CONTRACT", "PAYMENT", "DONE"];

function stepOf(value: string | null): ProjectStage | undefined {
  return STEPS.find((s) => s === value);
}

function Total({ row }: { row: ProjectRow }) {
  if (!row.total) return <>—</>;
  return (
    <MoneyText
      value={row.total.amount}
      {...(row.total.currency === "UZS" ? {} : { currency: row.total.currency })}
    />
  );
}

/** Документы проекта в строке: статусы договора, счёта и акта словами; проблемы — красными тегами. */
function Documents({ row }: { row: ProjectRow }) {
  const { t } = useTranslation("projects");
  const { contract, invoice, act } = row.documents;
  if (!contract && !invoice && !act) {
    return <span className="pf-hint">{t("list.noDocuments")}</span>;
  }
  return (
    <>
      <ul className="pf-proj-docs">
        {contract ? (
          <li>
            <span className="pf-hint">{t("card.documents.contract")}</span>
            <ProjectStatusTag kind="contract" status={contract.status} />
          </li>
        ) : null}
        {invoice ? (
          <li>
            <span className="pf-hint">{t("card.documents.invoice")}</span>
            <ProjectStatusTag kind="invoice" status={invoice.status} />
          </li>
        ) : null}
        {act ? (
          <li>
            <span className="pf-hint">{t("card.documents.act")}</span>
            <ProjectStatusTag kind="act" status={act.status} />
          </li>
        ) : null}
      </ul>
    </>
  );
}

function Problems({ row }: { row: ProjectRow }) {
  const { t } = useTranslation("projects");
  if (row.problems.length === 0) return null;
  return (
    <div className="pf-proj-tags">
      {row.problems.map((problem) => (
        <StatusTag key={problem} tone="red">
          {t(`problem.${problem}`)}
        </StatusTag>
      ))}
    </div>
  );
}

function StepTag({ step }: { step: ProjectStage }) {
  const { t } = useTranslation("dictionary");
  return <StatusTag tone={step === "DONE" ? "green" : "blue"}>{t(`stage.${step}`)}</StatusTag>;
}

function Rows({ items }: { items: readonly ProjectRow[] }) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  const { mobile } = useViewport();

  if (mobile) {
    return (
      <ul className="pf-dec-cards" aria-label={t("list.caption")}>
        {items.map((row) => (
          <li key={row.number}>
            <div className="pf-dec-card-head">
              <Link className="pf-focusable pf-dec-number" to={projectPath(row.number)}>
                {row.number}
              </Link>
              <StepTag step={row.step} />
            </div>
            <p className="pf-dec-card-subject">{row.client_name}</p>
            <p className="pf-hint">{t(`clientStatus.${row.client_status}`)}</p>
            <Documents row={row} />
            <Problems row={row} />
            <div className="pf-dec-card-foot">
              <span className="pf-hint">{row.responsible?.name ?? "—"}</span>
              <LinkButton
                size="small"
                to={projectPath(row.number)}
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
      <table className="pf-dec-table pf-fixed-table" style={{ minWidth: tableMinWidth(COLS, 150) }}>
        <caption className="pf-sr-only">{t("list.caption")}</caption>
        <TableCols widths={COLS} />
        <thead>
          <tr>
            <th scope="col">{t("list.columns.number")}</th>
            <th scope="col">{t("list.columns.client")}</th>
            <th scope="col">{t("list.columns.step")}</th>
            <th scope="col">{t("list.columns.status")}</th>
            <th scope="col">{t("list.columns.documents")}</th>
            <th scope="col">{t("list.columns.due")}</th>
            <th scope="col">{t("list.columns.responsible")}</th>
            <th scope="col">
              <span className="pf-sr-only">{t("list.columns.action")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.number}>
              <td className="pf-num">
                <Link className="pf-focusable pf-dec-number" to={projectPath(row.number)}>
                  {row.number}
                </Link>
                <div className="pf-hint">
                  <Total row={row} />
                </div>
              </td>
              <td>
                {row.client_name}
                <div className="pf-hint">{row.title}</div>
              </td>
              <td>
                <StepTag step={row.step} />
                <Problems row={row} />
              </td>
              <td>{t(`clientStatus.${row.client_status}`)}</td>
              <td>
                <Documents row={row} />
              </td>
              <td className="pf-num">{row.due_date ? date(row.due_date) : "—"}</td>
              <td className="pf-ell" title={row.responsible?.name ?? undefined}>
                {row.responsible?.name ?? "—"}
              </td>
              <td>
                <LinkButton
                  size="small"
                  to={projectPath(row.number)}
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
 * EDS · Проекты (SPEC-v3 §7.3): таблица «ПР-номер · клиент · шаг · статус для клиента · документы · срок · ответственный» с
 * фильтрами «мои», «с проблемами», шаг пути и поиск. Источник — ERP; пустое состояние словами.
 */
export function ProjectList() {
  const { t } = useTranslation(["projects", "modules"]);
  const labels = useStateLabels();
  const ids = useId();
  const [params, setParams] = useSearchParams();
  const title = t("modules:eds.sections.projects");
  useDocumentTitle(title);

  const scope = scopeOf(params.get("scope"));
  const problems = params.get("problems") === "1";
  const step = stepOf(params.get("step"));
  const q = (params.get("q") ?? "").trim();
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const filtered = scope === "mine" || problems || step !== undefined || q !== "";

  const query = useListEdsProjects(
    {
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
      ...(scope === "mine" ? { mine: true } : {}),
      ...(problems ? { problems: true } : {}),
      ...(step ? { step } : {}),
      ...(q ? { q } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );

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

  const shownKey = useShownKey(query.queryKey, query.isPlaceholderData);
  let body;
  if (query.isPending) {
    body = <ListSkeleton rows={PAGE_SIZE} />;
  } else if (query.isError) {
    const error = query.error;
    const text =
      error instanceof ApiError && error.status === 403
        ? labels.forbidden
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
  } else if (query.data.items.length === 0) {
    body = filtered ? (
      <EmptyState
        title={t("list.empty.filtered.title")}
        text={t("list.empty.filtered.text")}
        action={
          <Button
            onClick={() => {
              setParams(new URLSearchParams(), { replace: true });
            }}
          >
            {t("list.empty.filtered.action")}
          </Button>
        }
      />
    ) : (
      <EmptyState title={t("list.empty.all.title")} text={t("list.empty.all.text")} />
    );
  } else {
    const data = query.data;
    body = (
      <>
        <Rows items={data.items} />
        <div className="pf-proj-pager">
          <span className="pf-hint" role="status">
            {t("list.total", { count: data.total })}
          </span>
          {data.total > PAGE_SIZE ? (
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={data.total}
              showSizeChanger={false}
              size="small"
              onChange={(next) => {
                change({ page: next === 1 ? null : String(next) });
              }}
            />
          ) : null}
        </div>
      </>
    );
  }

  return (
    <div className="pf-dec-page">
      <PageHeader title={title} subtitle={t("list.subtitle")} />
      <div className="pf-proj-filters" role="search" aria-label={t("list.filters")}>
        <Segmented
          aria-label={t("list.scope.label")}
          value={scope}
          options={[
            { value: "all", label: t("list.scope.all") },
            { value: "mine", label: t("list.scope.mine") },
          ]}
          onChange={(value) => {
            change({ scope: (value as Scope) === "all" ? null : value });
          }}
        />
        <Checkbox
          checked={problems}
          onChange={(event) => {
            change({ problems: event.target.checked ? "1" : null });
          }}
        >
          {t("list.problems")}
        </Checkbox>
        <div className="pf-fp-field">
          <label htmlFor={`${ids}-step`}>{t("list.step.label")}</label>
          <Select
            id={`${ids}-step`}
            value={step ?? ""}
            style={{ minWidth: 160 }}
            options={[
              { value: "", label: t("list.step.all") },
              ...STEPS.map((s) => ({ value: s, label: t(`dictionary:stage.${s}`) })),
            ]}
            onChange={(value) => {
              change({ step: value });
            }}
          />
        </div>
        <div className="pf-fp-field pf-proj-search">
          <label htmlFor={`${ids}-q`}>{t("list.search.label")}</label>
          <Input.Search
            id={`${ids}-q`}
            key={q}
            defaultValue={q}
            allowClear
            placeholder={t("list.search.placeholder")}
            onSearch={(value) => {
              change({ q: value.trim() || null });
            }}
          />
        </div>
      </div>
      <Card styles={{ body: { padding: 0 } }}>
        <DataBlock busy={query.isPlaceholderData} resetKey={shownKey}>
          {body}
        </DataBlock>
      </Card>
    </div>
  );
}
