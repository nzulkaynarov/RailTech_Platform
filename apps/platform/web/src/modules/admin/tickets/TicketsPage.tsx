import { keepPreviousData } from "@tanstack/react-query";
import { Button, Card, Pagination, Select, Skeleton, Table } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";
import { TICKET_STATUSES, TICKET_SUBJECTS } from "../../../features/tickets/ticketMeta";
import { TicketStatusTag } from "../../../features/tickets/ticketUi";
import type {
  ListTicketsParams,
  TicketRow,
  TicketStatus,
  TicketSubject,
} from "../../../shared/api/generated/model";
import { useListTickets } from "../../../shared/api/generated/platform-bff";
import { useCompactBlock } from "../../../shared/lib/useCompactBlock";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { TicketCard } from "./TicketCard";

import "../../../features/help/help.css";

const PATH = "/admin/tickets";
const PAGE = 50;
const TABLE_MIN_WIDTH = 700;

const hrefOf = (number: string) => `${PATH}/${encodeURIComponent(number)}?panel=open&tab=card`;

/**
 * Admin · Обращения сотрудников (W15-H7, UX-оценка P1-4): что коллеги пишут администратору с экрана «Нет доступа» и
 * из «Помощи». Список с фильтром по статусу и теме, карточка — в боковом окне без перехода (`/admin/tickets/ОБР-0012`),
 * ответ уходит автору в колокольчик и в Telegram. Читают администратор и директор; отвечает администратор.
 */
export function TicketsPage({ objectId }: { objectId?: string | undefined }) {
  const { t } = useTranslation("help");
  const format = useFormat();
  const { wide } = useViewport();
  const title = t("admin.listLabel");
  useDocumentTitle(title);
  const base = useId();

  // Таблица или список — по ширине самого блока, с запасом 40 px у порога (useCompactBlock).
  const { ref: blockRef, compact } = useCompactBlock(TABLE_MIN_WIDTH, !wide);

  const [status, setStatus] = useState<TicketStatus | undefined>();
  const [subject, setSubject] = useState<TicketSubject | undefined>();
  const [page, setPage] = useState(1);
  const filtered = status !== undefined || subject !== undefined;
  const query: ListTicketsParams = {
    limit: PAGE,
    offset: (page - 1) * PAGE,
    ...(status ? { status } : {}),
    ...(subject ? { subject } : {}),
  };
  const list = useListTickets(query, { query: { placeholderData: keepPreviousData } });
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const counts = list.data?.counts;
  const reset = () => {
    setStatus(undefined);
    setSubject(undefined);
    setPage(1);
  };

  const numberLink = (row: TicketRow) => (
    <Link
      to={hrefOf(row.number)}
      className="pf-help-link pf-focusable"
      aria-current={row.number === objectId ? "true" : undefined}
      aria-label={t("admin.open", { number: row.number })}
    >
      {row.number}
    </Link>
  );

  let body;
  if (list.isPending) {
    body = <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  } else if (list.isError) {
    body = (
      <EmptyState
        title={t("admin.loadError")}
        text={t("admin.loadErrorText")}
        action={
          <Button
            onClick={() => {
              void list.refetch();
            }}
          >
            {t("admin.retry")}
          </Button>
        }
      />
    );
  } else if (items.length === 0 && filtered) {
    body = (
      <EmptyState
        title={t("admin.noMatch")}
        text={t("admin.noMatchText")}
        action={<Button onClick={reset}>{t("admin.reset")}</Button>}
      />
    );
  } else if (items.length === 0) {
    body = <EmptyState title={t("admin.empty")} text={t("admin.emptyText")} />;
  } else if (compact) {
    body = (
      <ul
        className="pf-list"
        aria-label={t("admin.listLabel")}
        style={{ margin: 0, padding: 0, listStyle: "none" }}
      >
        {items.map((row) => (
          <li
            key={row.number}
            className={`pf-ticket-row${row.number === objectId ? " pf-ticket-row-selected" : ""}`}
          >
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {numberLink(row)}
              <TicketStatusTag status={row.status} />
            </div>
            <div>{t(`ticket.subject.${row.subject}`)}</div>
            <div className="pf-hint">
              {row.author.name} · {format.activity(row.updated_at)}
            </div>
            <div className="pf-hint">{row.preview}</div>
          </li>
        ))}
      </ul>
    );
  } else {
    body = (
      <Table<TicketRow>
        rowKey="number"
        dataSource={items}
        pagination={false}
        tableLayout="fixed"
        aria-label={t("admin.listLabel")}
        rowClassName={(row) => (row.number === objectId ? "pf-ticket-table-row-selected" : "")}
        columns={[
          {
            title: t("admin.columns.number"),
            key: "number",
            width: "14%",
            render: (_, row) => numberLink(row),
          },
          {
            title: t("admin.columns.subject"),
            key: "subject",
            width: "30%",
            render: (_, row) => (
              <div>
                <div>{t(`ticket.subject.${row.subject}`)}</div>
                <div className="pf-hint">{row.preview}</div>
              </div>
            ),
          },
          {
            title: t("admin.columns.author"),
            key: "author",
            width: "22%",
            render: (_, row) => (
              <div>
                <div>{row.author.name}</div>
                <div className="pf-hint">{row.author_role}</div>
              </div>
            ),
          },
          {
            title: t("admin.columns.status"),
            key: "status",
            width: "16%",
            render: (_, row) => <TicketStatusTag status={row.status} />,
          },
          {
            title: t("admin.columns.updated"),
            key: "updated",
            width: "18%",
            render: (_, row) => format.activity(row.updated_at),
          },
        ]}
      />
    );
  }

  return (
    <>
      <PageHeader title={title} subtitle={t("admin.subtitle")} />
      <div ref={blockRef}>
        <Card styles={{ body: { padding: 0 } }}>
          <form
            className="pf-ticket-filters"
            role="search"
            aria-label={t("admin.filtersLabel")}
            onSubmit={(event) => {
              event.preventDefault();
            }}
          >
            <div className="pf-ticket-field">
              <label htmlFor={`${base}-status`}>{t("admin.status")}</label>
              <Select<TicketStatus>
                id={`${base}-status`}
                allowClear
                placeholder={t("admin.allStatuses")}
                style={{ minWidth: 180 }}
                value={status}
                options={TICKET_STATUSES.map((value) => ({
                  value,
                  label: t(`ticket.status.${value}`),
                }))}
                onChange={(value?: TicketStatus) => {
                  setStatus(value);
                  setPage(1);
                }}
              />
            </div>
            <div className="pf-ticket-field">
              <label htmlFor={`${base}-subject`}>{t("admin.subject")}</label>
              <Select<TicketSubject>
                id={`${base}-subject`}
                allowClear
                placeholder={t("admin.allSubjects")}
                style={{ minWidth: 220 }}
                value={subject}
                options={TICKET_SUBJECTS.map((value) => ({
                  value,
                  label: t(`ticket.subject.${value}`),
                }))}
                onChange={(value?: TicketSubject) => {
                  setSubject(value);
                  setPage(1);
                }}
              />
            </div>
            {filtered ? <Button onClick={reset}>{t("admin.reset")}</Button> : null}
            {counts ? (
              <span className="pf-hint" aria-live="polite" style={{ marginLeft: "auto" }}>
                {t("admin.countsNew", { count: counts.new })} ·{" "}
                {t("admin.countsWork", { count: counts.in_progress })} ·{" "}
                {t("admin.countsDone", { count: counts.resolved })}
              </span>
            ) : null}
          </form>
          {body}
          {list.data && total > PAGE ? (
            <div className="pf-ticket-footer">
              <span className="pf-hint">{t("admin.total", { count: total })}</span>
              <Pagination
                current={page}
                pageSize={PAGE}
                total={total}
                showSizeChanger={false}
                size="small"
                aria-label={t("admin.pager")}
                onChange={setPage}
              />
            </div>
          ) : null}
        </Card>
      </div>
      <PanelPortal tab="card">
        {objectId ? (
          <TicketCard key={objectId} number={objectId} />
        ) : (
          <EmptyState
            level={3}
            compact
            title={t("admin.card.hintTitle")}
            text={t("admin.card.hint")}
          />
        )}
      </PanelPortal>
    </>
  );
}
