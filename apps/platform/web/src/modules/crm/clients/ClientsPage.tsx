import { Card, Input, Segmented, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { ClientRow } from "../../../shared/api/generated/model";
import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import {
  useListCrmClients,
  useListStockSuppliers,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { Sheet } from "../common/Sheet";
import { parseClientId, useParamChanger, withParams } from "../common/params";
import { CreateRequest } from "../request/CreateRequest";
import { ClientPanel } from "./ClientPanel";

import "../crm.css";

/** Ширины колонок: название, ИНН, заявки, ERP, последняя активность (UX-1c, S9; по типу — platform-frontend.md §4.2) */
const COLS = [null, 140, 150, 144, 170, 184] as const;

const KINDS = ["all", "clients", "partners"] as const;
type KindFilter = (typeof KINDS)[number];
type RelationKind = "client" | "partner" | "both";

/** Партнёр без клиента: строка той же формы, отрицательный id отличает её от клиента CRM. */
function isPartnerOnly(row: ClientRow): boolean {
  return row.id < 0;
}

function RelationTag({ kind }: { kind: RelationKind }) {
  const { t } = useTranslation("clients");
  return <Tag>{t(`kinds.${kind}`)}</Tag>;
}

function ErpTag({ row }: { row: ClientRow }) {
  const { t } = useTranslation("clients");
  if (isPartnerOnly(row)) return <span aria-hidden="true">—</span>;
  if (row.handoff_status === "failed")
    return (
      <StatusTag kind="access" status="error">
        {t("handoff.failed")}
      </StatusTag>
    );
  if (row.handoff_status === "pending")
    return (
      <StatusTag kind="access" status="pending">
        {t("handoff.pending")}
      </StatusTag>
    );
  return row.in_erp ? (
    <StatusTag kind="access" status="yes">
      {t("inErp")}
    </StatusTag>
  ) : (
    <StatusTag kind="access" status="no">
      {t("notInErp")}
    </StatusTag>
  );
}

function NameLink({
  row,
  params,
  selected,
}: {
  row: ClientRow;
  params: URLSearchParams;
  selected: boolean;
}) {
  const { t } = useTranslation("clients");
  const { mobile } = useViewport();
  if (isPartnerOnly(row)) {
    return (
      <Link
        className="pf-crm-link pf-focusable"
        to={`/erp/catalog?part=suppliers&supplier=${String(-row.id)}`}
        aria-label={t("open", { name: row.name })}
      >
        {row.name}
      </Link>
    );
  }
  return (
    <Link
      className="pf-crm-link pf-focusable"
      to={`/crm/clients${withParams(params, {
        client: String(row.id),
        create: null,
        panel: mobile ? null : "open",
        tab: mobile ? null : "card",
      })}`}
      aria-label={t("open", { name: row.name })}
      aria-current={selected ? "true" : undefined}
    >
      {row.name}
    </Link>
  );
}

function Activity({ row }: { row: ClientRow }) {
  const fmt = useFormat();
  return row.last_activity_at ? (
    <span>{fmt.activity(row.last_activity_at)}</span>
  ) : (
    <span aria-hidden="true">—</span>
  );
}

/**
 * Клиенты · Клиенты (SPEC-v3 §7.2): список компаний с поиском по названию и ИНН; клик — карточка 360° в боковом окне (на
 * телефоне — лист на весь экран), оттуда «Новая заявка для клиента». Адрес `/crm/clients/42` (поиск ⌘K) и `?client=42`
 * открывают карточку.
 */
export function ClientsPage({ objectId }: { objectId?: string | undefined }) {
  const { t } = useTranslation(["clients", "modules", "request"]);
  const { mobile } = useViewport();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const change = useParamChanger();
  const title = t("modules:crm.sections.clients");
  useDocumentTitle(title);
  const q = params.get("q") ?? "";
  const { me } = useAuth();
  const list = useListCrmClients(q ? { q } : {});
  const suppliers = useListStockSuppliers(q ? { q } : undefined, {
    query: { enabled: canSee(me, { resource: "erp.stock" }) },
  });
  const askedKind = params.get("kind");
  const kind: KindFilter = KINDS.find((value) => value === askedKind) ?? "all";
  const partnerInns = new Set((suppliers.data?.items ?? []).flatMap((s) => s.inn ?? []));
  const relationOf = (row: ClientRow): RelationKind => {
    if (isPartnerOnly(row)) return "partner";
    return row.inn && partnerInns.has(row.inn) ? "both" : "client";
  };
  const rowsOf = (clients: readonly ClientRow[]): ClientRow[] => {
    const clientInns = new Set(clients.flatMap((c) => c.inn ?? []));
    const partners = (suppliers.data?.items ?? [])
      .filter((s) => !s.inn || !clientInns.has(s.inn))
      .map((s): ClientRow => ({
        id: -Number(s.id),
        name: s.name,
        inn: s.inn,
        in_erp: true,
        open_requests: 0,
        last_activity_at: null,
        handoff_status: null,
      }));
    const all = [...clients, ...partners];
    if (kind === "clients") return all.filter((row) => relationOf(row) !== "partner");
    if (kind === "partners") return all.filter((row) => relationOf(row) !== "client");
    return all;
  };
  const selected = parseClientId(objectId) ?? parseClientId(params.get("client"));
  const creating = selected !== null && params.get("create") === "1";

  const close = () => {
    if (objectId !== undefined) {
      const next = new URLSearchParams(params);
      for (const key of ["client", "create", "panel", "tab"]) next.delete(key);
      const text = next.toString();
      void navigate(`/crm/clients${text ? `?${text}` : ""}`, { replace: true });
      return;
    }
    change({ client: null, create: null, panel: null, tab: null });
  };

  const labels = {
    retry: t("clients:retry"),
    loadError: { title: t("clients:loadError.title"), text: t("clients:loadError.text") },
    unavailable: { title: t("clients:loadError.title"), text: t("clients:loadError.text") },
    forbidden: { title: t("clients:loadError.title"), text: t("clients:loadError.text") },
  };

  return (
    <div className="pf-crm">
      <PageHeader title={title} />
      <div className="pf-crm-controls">
        <Segmented
          aria-label={t("clients:kinds.filter")}
          value={kind}
          options={KINDS.map((value) => ({ value, label: t(`clients:kinds.${value}`) }))}
          onChange={(value) => {
            change({ kind: value === "all" ? null : value });
          }}
        />
        <div className="pf-crm-filter pf-crm-search">
          <label htmlFor="pf-clients-q">{t("clients:search.label")}</label>
          <Input.Search
            id="pf-clients-q"
            defaultValue={q}
            allowClear
            placeholder={t("clients:search.placeholder")}
            onSearch={(value) => {
              change({ q: value.trim() ? value.trim() : null });
            }}
          />
        </div>
      </div>
      <Card styles={{ body: { padding: 0 } }}>
        <QueryState query={list} labels={labels} rows={20}>
          {(data) =>
            rowsOf(data.items).length === 0 ? (
              <EmptyState
                title={t(q ? "clients:empty.filteredTitle" : "clients:empty.title")}
                text={t(q ? "clients:empty.filteredText" : "clients:empty.text")}
              />
            ) : mobile ? (
              <ul className="pf-crm-list" aria-label={t("clients:listLabel")}>
                {rowsOf(data.items).map((row) => (
                  <li key={row.id} className="pf-crm-item" data-selected={selected === row.id}>
                    <div className="pf-crm-item-head">
                      <RelationTag kind={relationOf(row)} />
                      <ErpTag row={row} />
                    </div>
                    <NameLink row={row} params={params} selected={selected === row.id} />
                    <div className="pf-crm-item-meta">
                      {row.inn ? (
                        <span>
                          {t("clients:columns.inn")} {row.inn}
                        </span>
                      ) : null}
                      <span>
                        {t("clients:columns.requests")}: {row.open_requests}
                      </span>
                      <Activity row={row} />
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <ScrollRegion label={t("clients:tableScroll")}>
                <table
                  className="pf-crm-table pf-fixed-table"
                  style={{ minWidth: tableMinWidth(COLS, 240) }}
                >
                  <caption className="pf-sr-only">{t("clients:caption")}</caption>
                  <TableCols widths={COLS} />
                  <thead>
                    <tr>
                      <th scope="col">{t("clients:columns.name")}</th>
                      <th scope="col">{t("clients:columns.inn")}</th>
                      <th scope="col">{t("clients:kinds.column")}</th>
                      <th scope="col" className="pf-col-num">
                        {t("clients:columns.requests")}
                      </th>
                      <th scope="col">{t("clients:columns.erp")}</th>
                      <th scope="col">{t("clients:columns.last")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rowsOf(data.items).map((row) => (
                      <tr key={row.id} data-selected={selected === row.id}>
                        <td className="pf-crm-wrap">
                          <NameLink row={row} params={params} selected={selected === row.id} />
                        </td>
                        <td className="pf-num">{row.inn ?? <span aria-hidden="true">—</span>}</td>
                        <td>
                          <RelationTag kind={relationOf(row)} />
                        </td>
                        <td className="pf-col-num">{row.open_requests}</td>
                        <td>
                          <ErpTag row={row} />
                        </td>
                        <td>
                          <Activity row={row} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
            )
          }
        </QueryState>
      </Card>
      {selected !== null ? (
        <Sheet label={t(creating ? "request:title" : "clients:card.label")} onClose={close}>
          {creating ? (
            <CreateRequest
              key={`create-${String(selected)}`}
              lead={null}
              clientId={selected}
              onCancel={() => {
                change({ create: null });
              }}
            />
          ) : (
            <ClientPanel key={selected} id={selected} onClose={close} />
          )}
        </Sheet>
      ) : null}
    </div>
  );
}
