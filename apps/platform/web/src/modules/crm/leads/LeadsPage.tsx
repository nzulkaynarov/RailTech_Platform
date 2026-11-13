import { Button, Card, Input, Segmented, Select } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import type {
  LeadRow,
  ListCrmLeadsParams,
  ListCrmLeadsScope,
  ListCrmLeadsTab,
} from "../../../shared/api/generated/model";
import { useListCrmLeads, useTakeCrmLead } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ErrorNote, QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { TabsBar } from "../../../shared/ui/TabsBar";
import { actionError, channelLabel } from "../messages/labels";
import { canCreateFromLead } from "../common/access";
import { Sheet } from "../../../shared/ui/Sheet";
import {
  clientPath,
  parseLead,
  useParamChanger,
  useRefreshCrm,
  withParams,
} from "../common/params";
import { CreateRequest } from "../request/CreateRequest";
import { NewLeadForm } from "./NewLeadForm";
import { Conversations } from "../messages/MessagesPage";
import { LeadPanel } from "./LeadPanel";

import "../crm.css";

const PAGE_SIZE = 50;
const TABS = [
  "all",
  "new",
  "dialog",
  "wants_quote",
  "client",
] as const satisfies readonly ListCrmLeadsTab[];
const SCOPES = ["all", "mine", "overdue"] as const satisfies readonly ListCrmLeadsScope[];
/** Переключатель над списком: «Ждут ответа» — не отбор лидов, а переписка, где клиент ждёт ответа */
const VIEWS = ["all", "mine", "waiting", "overdue"] as const;
type View = (typeof VIEWS)[number];
const CHANNELS = ["telegram", "cabinet", "web", "email", "phone", "referral"] as const;
/** Ширины колонок: имя, статус, что нужно, ответственный, последнее, действие (UX-1c, S9) */
const COLS = {
  status: 150,
  assigned: 170,
  last: 130,
  action: 170,
};

function pick<T extends string>(list: readonly T[], value: string | null, fallback: T): T {
  return list.find((item) => item === value) ?? fallback;
}

/**
 * Действие строки по статусу (SPEC-v3 §7.2): «Просит КП» — главная «Создать заявку»; открытая передача от бота —
 * «Забрать» (и сразу в «Ждут ответа»); переписка — «Ответить»; клиент — его карточка.
 */
function RowAction({ row, onError }: { row: LeadRow; onError: (text: string | null) => void }) {
  const { t } = useTranslation(["leads", "messages"]);
  const { me } = useAuth();
  const navigate = useNavigate();
  const refresh = useRefreshCrm();
  const take = useTakeCrmLead();
  const canReply = canEdit(me, "crm.leads");
  const canCreate = canCreateFromLead(me, row.assigned);
  const [params] = useSearchParams();
  const toDialog = `/crm/leads?scope=waiting&lead=${row.lead}`;
  if (row.status === "wants_quote" && canCreate) {
    return (
      <LinkButton
        type="primary"
        size="small"
        to={`/crm/leads${withParams(params, { lead: row.lead, create: "1", panel: "open", tab: "card" })}`}
        aria-label={t("leads:actions.createLabel", { name: row.name })}
      >
        {t("leads:actions.create")}
      </LinkButton>
    );
  }
  if (row.status === "client" && row.client_id !== null) {
    return (
      <LinkButton
        size="small"
        to={clientPath(row.client_id)}
        aria-label={t("leads:actions.clientLabel", { name: row.name })}
      >
        {t("leads:actions.client")}
      </LinkButton>
    );
  }
  if (!canReply && canEdit(me, "crm.leads.triage") && !row.assigned && row.status !== "lost") {
    // Первая линия (D17G-1): «Разобрать» — в диалог, где «Передать менеджеру» с запиской.
    return (
      <LinkButton
        size="small"
        to={toDialog}
        aria-label={t("leads:actions.triageLabel", { name: row.name })}
      >
        {t("leads:actions.triage")}
      </LinkButton>
    );
  }
  if (!canReply || row.status === "lost") return null;
  if (row.handoff_open) {
    return (
      <Button
        size="small"
        loading={take.isPending}
        aria-label={t("leads:actions.takeLabel", { name: row.name })}
        onClick={() => {
          onError(null);
          take.mutate(
            { lead: row.lead },
            {
              onSuccess: () => {
                refresh();
                void navigate(toDialog);
              },
              onError: (error) => {
                onError(actionError(t, error));
              },
            },
          );
        }}
      >
        {t("leads:actions.take")}
      </Button>
    );
  }
  return (
    <LinkButton
      size="small"
      to={toDialog}
      aria-label={t("leads:actions.replyLabel", { name: row.name })}
    >
      {t("leads:actions.reply")}
    </LinkButton>
  );
}

function NameCell({
  row,
  params,
  selected,
}: {
  row: LeadRow;
  params: URLSearchParams;
  selected: boolean;
}) {
  const { t } = useTranslation("leads");
  const { mobile } = useViewport();
  return (
    <span className="pf-crm-name">
      <Link
        className="pf-crm-link pf-focusable"
        to={`/crm/leads${withParams(params, {
          lead: row.lead,
          create: null,
          panel: mobile ? null : "open",
          tab: mobile ? null : "card",
        })}`}
        aria-label={t("open", { name: row.name })}
        aria-current={selected ? "true" : undefined}
      >
        {row.name}
      </Link>
      {row.unread ? <StatusTag tone="blue">{t("unread")}</StatusTag> : null}
      {row.overdue ? <StatusTag tone="red">{t("overdue")}</StatusTag> : null}
    </span>
  );
}

function LastMessage({ row }: { row: LeadRow }) {
  const fmt = useFormat();
  return row.last_message_at ? (
    <span>{fmt.activity(row.last_message_at)}</span>
  ) : (
    <span aria-hidden="true">—</span>
  );
}

function LeadsTable({
  items,
  selected,
  params,
  onError,
}: {
  items: readonly LeadRow[];
  selected: string | null;
  params: URLSearchParams;
  onError: (text: string | null) => void;
}) {
  const { t } = useTranslation(["leads", "messages"]);
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<LeadRow>[] = [
    {
      id: "name",
      header: t("leads:columns.name"),
      width: null,
      cell: (row) => (
        <>
          <NameCell row={row} params={params} selected={selected === row.lead} />
          <div className="pf-hint">
            {row.lead} · {channelLabel(t, row.channel)}
          </div>
        </>
      ),
    },
    {
      id: "status",
      header: t("leads:columns.status"),
      width: COLS.status,
      cell: (row) => (
        <>
          <StatusTag kind="lead" status={row.status} />
        </>
      ),
    },
    {
      id: "need",
      header: t("leads:columns.need"),
      width: null,
      cellClassName: "pf-crm-need",
      cell: (row) => row.need ?? <span aria-hidden="true">—</span>,
    },
    {
      id: "assigned",
      header: t("leads:columns.assigned"),
      width: COLS.assigned,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.assigned?.name ?? t("leads:nobody"),
      cell: (row) => row.assigned?.name ?? t("leads:nobody"),
    },
    {
      id: "last",
      header: t("leads:columns.last"),
      width: COLS.last,
      cell: (row) => (
        <>
          <LastMessage row={row} />
        </>
      ),
    },
    {
      id: "action",
      header: t("leads:columns.action"),
      width: COLS.action,
      cell: (row) => (
        <>
          <RowAction row={row} onError={onError} />
        </>
      ),
    },
  ];
  return (
    <DataTable
      tableId="crm.leads"
      caption={t("leads:caption")}
      scrollLabel={t("leads:tableScroll")}
      className="pf-crm-table"
      flexMin={200}
      columns={columns}
      rows={items}
      rowKey={(row) => row.lead}
      rowAttrs={(row) => ({
        "data-selected": selected === row.lead,
      })}
    />
  );
}

function LeadsList({
  items,
  selected,
  params,
  onError,
}: {
  items: readonly LeadRow[];
  selected: string | null;
  params: URLSearchParams;
  onError: (text: string | null) => void;
}) {
  const { t } = useTranslation(["leads", "messages"]);
  return (
    <ul className="pf-crm-list" aria-label={t("leads:listLabel")}>
      {items.map((row) => (
        <li key={row.lead} className="pf-crm-item" data-selected={selected === row.lead}>
          <div className="pf-crm-item-head">
            <StatusTag kind="lead" status={row.status} />
            <span className="pf-hint">{row.lead}</span>
          </div>
          <NameCell row={row} params={params} selected={selected === row.lead} />
          {row.need ? <div className="pf-crm-need">{row.need}</div> : null}
          <div className="pf-crm-item-meta">
            <span>{channelLabel(t, row.channel)}</span>
            <span>{row.assigned?.name ?? t("leads:nobody")}</span>
            <LastMessage row={row} />
          </div>
          <div>
            <RowAction row={row} onError={onError} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Клиенты · Лиды (SPEC-v3 §7.2): вкладки по статусу, «Мои / Все / Просроченные», канал и поиск; действие строки — по
 * статусу. Клик по имени — карточка лида в боковом окне, «Создать заявку» — форма там же (на телефоне — лист на весь
 * экран). Адрес `/crm/leads/L-2041` и `?lead=L-2041` открывают карточку (поиск ⌘K, колокольчик, очередь).
 */
export function LeadsPage({ objectId }: { objectId?: string | undefined }) {
  const { t } = useTranslation(["leads", "modules", "messages"]);
  const { mobile } = useViewport();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const change = useParamChanger();
  const title = t("modules:crm.sections.leads");
  useDocumentTitle(title);
  const [actionFailure, setActionFailure] = useState<string | null>(null);

  const tab = pick(TABS, params.get("status"), "all");
  const view: View = pick(VIEWS, params.get("scope"), "all");
  const waiting = view === "waiting";
  const scope = waiting ? "all" : pick(SCOPES, view, "all");
  const channel = pick(["", ...CHANNELS], params.get("channel"), "");
  const q = params.get("q") ?? "";
  const offset = Math.max(0, Number(params.get("offset") ?? "0") || 0);
  const lead = parseLead(objectId) ?? parseLead(params.get("lead"));
  const creating = lead !== null && params.get("create") === "1";
  // «Создать · Лид» из окна «Создать» (план 2026-11-12 п. 0.1)
  const newLead = lead === null && params.get("new") === "1";
  // «В заявку» у файла клиента в «Ждут ответа»: `letter=<сообщение>-<вложение>`
  const letterHit = /^(\d{1,12})-(\d{1,3})$/.exec(params.get("letter") ?? "");
  const letterFrom = letterHit
    ? { message: Number(letterHit[1]), index: Number(letterHit[2]) }
    : null;

  const query: ListCrmLeadsParams = useMemo(
    () => ({
      tab,
      scope,
      ...(channel ? { channel } : {}),
      ...(q ? { q } : {}),
      offset,
      limit: PAGE_SIZE,
    }),
    [tab, scope, channel, q, offset],
  );
  const list = useListCrmLeads(query, { query: { enabled: !waiting } });
  const filtered = tab !== "all" || scope !== "all" || channel !== "" || q !== "";

  const close = () => {
    if (objectId !== undefined) {
      const next = new URLSearchParams(params);
      for (const key of ["lead", "create", "letter", "panel", "tab"]) next.delete(key);
      const text = next.toString();
      void navigate(`/crm/leads${text ? `?${text}` : ""}`, { replace: true });
      return;
    }
    change({ lead: null, create: null, letter: null, panel: null, tab: null });
  };

  const labels = {
    retry: t("leads:retry"),
    loadError: { title: t("leads:loadError.title"), text: t("leads:loadError.text") },
    unavailable: { title: t("leads:loadError.title"), text: t("leads:loadError.text") },
    forbidden: { title: t("leads:loadError.title"), text: t("leads:loadError.text") },
  };

  const body = (
    <QueryState query={list} labels={labels} rows={PAGE_SIZE}>
      {(data) =>
        data.items.length === 0 ? (
          <EmptyState
            title={t(filtered ? "leads:empty.filteredTitle" : "leads:empty.title")}
            text={t(filtered ? "leads:empty.filteredText" : "leads:empty.text")}
          />
        ) : (
          <>
            {mobile ? (
              <LeadsList
                items={data.items}
                selected={lead}
                params={params}
                onError={setActionFailure}
              />
            ) : (
              <LeadsTable
                items={data.items}
                selected={lead}
                params={params}
                onError={setActionFailure}
              />
            )}
            {data.total > PAGE_SIZE ? (
              <nav className="pf-crm-pager" aria-label={t("leads:paging.label")}>
                <Button
                  disabled={offset === 0}
                  onClick={() => {
                    change({ offset: offset - PAGE_SIZE > 0 ? String(offset - PAGE_SIZE) : null });
                  }}
                >
                  {t("leads:paging.prev")}
                </Button>
                <span className="pf-hint">
                  {t("leads:paging.range", {
                    from: offset + 1,
                    to: Math.min(offset + PAGE_SIZE, data.total),
                    total: data.total,
                  })}
                </span>
                <Button
                  disabled={offset + PAGE_SIZE >= data.total}
                  onClick={() => {
                    change({ offset: String(offset + PAGE_SIZE) });
                  }}
                >
                  {t("leads:paging.next")}
                </Button>
              </nav>
            ) : null}
          </>
        )
      }
    </QueryState>
  );

  const viewSwitch = (
    <Segmented
      aria-label={t("leads:scope.label")}
      value={view}
      options={VIEWS.map((value) => ({ value, label: t(`leads:scope.${value}`) }))}
      onChange={(value) => {
        change({
          scope: value === "all" ? null : value,
          offset: null,
          lead: null,
          panel: null,
          tab: null,
        });
      }}
    />
  );

  if (waiting) {
    return (
      <div className="pf-crm">
        {mobile && lead ? null : (
          <>
            <PageHeader title={title} />
            <div className="pf-crm-controls">{viewSwitch}</div>
          </>
        )}
        <Conversations />
      </div>
    );
  }

  return (
    <div className="pf-crm">
      <PageHeader title={title} />
      <div className="pf-crm-controls">
        {viewSwitch}
        {mobile ? (
          <div className="pf-crm-filter">
            <label htmlFor="pf-leads-tab">{t("leads:tabs.label")}</label>
            <Select
              id="pf-leads-tab"
              style={{ minWidth: 160 }}
              value={tab}
              options={TABS.map((value) => ({ value, label: t(`leads:tabs.${value}`) }))}
              onChange={(value) => {
                change({ status: value === "all" ? null : value, offset: null });
              }}
            />
          </div>
        ) : null}
        <div className="pf-crm-filter">
          <label htmlFor="pf-leads-channel">{t("leads:channel.label")}</label>
          <Select
            id="pf-leads-channel"
            style={{ minWidth: 160 }}
            value={channel}
            options={[
              { value: "", label: t("leads:channel.any") },
              ...CHANNELS.map((value) => ({ value, label: channelLabel(t, value) })),
            ]}
            onChange={(value) => {
              change({ channel: value === "" ? null : value, offset: null });
            }}
          />
        </div>
        <div className="pf-crm-filter pf-crm-search">
          <label htmlFor="pf-leads-q">{t("leads:search.label")}</label>
          <Input.Search
            id="pf-leads-q"
            defaultValue={q}
            allowClear
            placeholder={t("leads:search.placeholder")}
            onSearch={(value) => {
              change({ q: value.trim() ? value.trim() : null, offset: null });
            }}
          />
        </div>
      </div>
      <ErrorNote message={actionFailure} />
      <Card styles={{ body: { padding: 0 } }}>
        {mobile ? (
          body
        ) : (
          <TabsBar
            id="pf-leads-tabs"
            label={t("leads:tabs.label")}
            activeKey={tab}
            onChange={(key) => {
              change({ status: key === "all" ? null : key, offset: null });
            }}
            tabBarStyle={{ margin: 0, padding: "0 16px" }}
            items={TABS.map((key) => ({ key, label: t(`leads:tabs.${key}`) }))}
          >
            {body}
          </TabsBar>
        )}
      </Card>
      {newLead ? (
        <Sheet
          label={t("leads:newLead.title")}
          onClose={() => {
            change({ new: null, panel: null, tab: null });
          }}
        >
          <NewLeadForm
            onCancel={() => {
              change({ new: null, panel: null, tab: null });
            }}
          />
        </Sheet>
      ) : null}
      {lead ? (
        <Sheet label={t(creating ? "request:title" : "leads:card.label")} onClose={close}>
          {creating ? (
            <CreateRequest
              key={`create-${lead}`}
              lead={lead}
              clientId={null}
              letterFrom={letterFrom}
              onCancel={() => {
                change({ create: null, letter: null });
              }}
            />
          ) : (
            <LeadPanel key={lead} lead={lead} onClose={close} />
          )}
        </Sheet>
      ) : null}
    </div>
  );
}
