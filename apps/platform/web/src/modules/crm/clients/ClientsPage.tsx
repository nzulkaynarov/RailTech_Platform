import { Button, Card, Input, Segmented, Tag } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { ClientRow } from "../../../shared/api/generated/model";
import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import {
  useListBankChangeRequests,
  useListCatalogSuppliers,
  useListCrmClients,
  useListPartnerApplications,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { BankChangesPanel } from "../../eds/payments/BankChangesPanel";
import { PartnerApplicationsPanel } from "../../erp/catalog/PartnerApplicationsPanel";
import { PartnerCard } from "../../erp/catalog/PartnerCard";
import { SupplierForm } from "../../erp/catalog/supplierForms";
import { Sheet } from "../common/Sheet";
import { parseClientId, useParamChanger, withParams } from "../common/params";
import { CreateRequest } from "../request/CreateRequest";
import { ClientPanel } from "./ClientPanel";

import "../../eds/payments/payments.css";
import "../../erp/catalog/catalog.css";
import "../crm.css";

/** Ширины колонок: название, ИНН, заявки, ERP, последняя активность (UX-1c, S9; по типу — platform-frontend.md §4.2) */
const COLS = {
  inn: 140,
  kind: 150,
  requests: 144,
  erp: 170,
  last: 184,
};

const KINDS = ["all", "clients", "partners", "applications", "bank_changes"] as const;
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

/** Сроки цен партнёра: то, что снабжению нужно видеть в списке. */
interface PriceTerms {
  expired_count: number;
  expiring_count: number;
}

function PriceTermsTag({ terms }: { terms: PriceTerms | undefined }) {
  const { t } = useTranslation("catalog");
  if (!terms) return <span aria-hidden="true">—</span>;
  if (terms.expired_count > 0)
    return (
      <StatusTag kind="validity" status="expired">
        {t("suppliers.expired", { count: terms.expired_count })}
      </StatusTag>
    );
  if (terms.expiring_count > 0)
    return (
      <StatusTag kind="validity" status="expiring">
        {t("suppliers.expiring", { count: terms.expiring_count })}
      </StatusTag>
    );
  return (
    <StatusTag kind="validity" status="ok">
      {t("suppliers.allValid")}
    </StatusTag>
  );
}

function StateTag({ row, terms }: { row: ClientRow; terms: PriceTerms | undefined }) {
  const { t } = useTranslation("clients");
  if (isPartnerOnly(row)) return <PriceTermsTag terms={terms} />;
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
  const partner = isPartnerOnly(row);
  return (
    <Link
      className="pf-crm-link pf-focusable"
      to={`/crm/clients${withParams(params, {
        client: partner ? null : String(row.id),
        partner: partner ? String(-row.id) : null,
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
  const seesPartners = canSee(me, { resource: "erp.stock" });
  // 0.3 (FR-13): снабженец без `crm.clients` — только партнёры каталога; клиентов CRM не запрашиваем.
  const seesClients = canSee(me, { resource: "crm.clients" });
  const seesBankChanges = canSee(me, { resource: "eds.payments" });
  const list = useListCrmClients(q ? { q } : {}, { query: { enabled: seesClients } });
  const suppliers = useListCatalogSuppliers(
    { ...(q ? { q } : {}), page: 1, page_size: 200 },
    { query: { enabled: seesPartners } },
  );
  // Без `crm.clients` список строится только из партнёров каталога: ожидание и сбой — по запросу поставщиков.
  const partnersOnly = {
    isPending: suppliers.isPending,
    isError: suppliers.isError,
    error: suppliers.error,
    data: suppliers.data ? { items: [] as ClientRow[] } : undefined,
    refetch: suppliers.refetch,
    queryKey: suppliers.queryKey,
  };
  const termsOf = new Map((suppliers.data?.items ?? []).map((row) => [row.id, row]));
  const applications = useListPartnerApplications(
    { status: "submitted" },
    { query: { enabled: seesPartners } },
  );
  const bankChanges = useListBankChangeRequests(
    { status: "pending" },
    { query: { enabled: seesBankChanges } },
  );
  const [addingPartner, setAddingPartner] = useState(false);
  const shownKinds = KINDS.filter((value) => {
    if (value === "partners" || value === "applications") return seesPartners;
    if (value === "bank_changes") return seesBankChanges;
    return seesClients; // «Все» и «Клиенты» — только тем, кто видит клиентов
  });
  const askedKind = params.get("kind");
  const kind: KindFilter =
    shownKinds.find((value) => value === askedKind) ?? shownKinds[0] ?? "all";
  const kindLabel = (value: KindFilter): string => {
    if (value === "applications" && applications.data?.pending_count) {
      return `${t("clients:kinds.applications")} · ${String(applications.data.pending_count)}`;
    }
    if (value === "bank_changes" && bankChanges.data?.pending_count) {
      return `${t("clients:kinds.bank_changes")} · ${String(bankChanges.data.pending_count)}`;
    }
    return t(`clients:kinds.${value}`);
  };
  const partnerInns = new Set((suppliers.data?.items ?? []).flatMap((s) => s.tin || []));
  const relationOf = (row: ClientRow): RelationKind => {
    if (isPartnerOnly(row)) return "partner";
    return row.inn && partnerInns.has(row.inn) ? "both" : "client";
  };
  const rowsOf = (clients: readonly ClientRow[]): ClientRow[] => {
    const clientInns = new Set(clients.flatMap((c) => c.inn ?? []));
    const partners = (suppliers.data?.items ?? [])
      .filter((s) => !s.tin || !clientInns.has(s.tin))
      .map((s): ClientRow => ({
        id: -Number(s.id),
        name: s.name,
        inn: s.tin || null,
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
  const partner = params.get("partner");
  const selectedInn = list.data?.items.find((row) => row.id === selected)?.inn;
  const sameCompanyPartner = selectedInn
    ? suppliers.data?.items.find((row) => row.tin === selectedInn)
    : undefined;
  const creating = selected !== null && params.get("create") === "1";
  // «Создать · Заявка» из окна «Создать» (план 2026-11-12 п. 0.1): клиент выбирается в самой форме.
  const newRequest = selected === null && params.get("create") === "1";

  const isOpen = (row: ClientRow): boolean =>
    isPartnerOnly(row) ? partner === String(-row.id) : selected === row.id;

  const close = () => {
    if (objectId !== undefined) {
      const next = new URLSearchParams(params);
      for (const key of ["client", "partner", "create", "panel", "tab"]) next.delete(key);
      const text = next.toString();
      void navigate(`/crm/clients${text ? `?${text}` : ""}`, { replace: true });
      return;
    }
    change({ client: null, partner: null, create: null, panel: null, tab: null });
  };

  const queue = kind === "applications" || kind === "bank_changes";

  const labels = {
    retry: t("clients:retry"),
    loadError: { title: t("clients:loadError.title"), text: t("clients:loadError.text") },
    unavailable: { title: t("clients:loadError.title"), text: t("clients:loadError.text") },
    forbidden: { title: t("clients:loadError.title"), text: t("clients:loadError.text") },
  };

  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<ClientRow>[] = [
    {
      id: "name",
      header: t("clients:columns.name"),
      width: null,
      cellClassName: "pf-crm-wrap",
      cell: (row) => (
        <>
          <NameLink row={row} params={params} selected={isOpen(row)} />
        </>
      ),
    },
    {
      id: "inn",
      header: t("clients:columns.inn"),
      width: COLS.inn,
      cellClassName: "pf-num",
      cell: (row) => row.inn ?? <span aria-hidden="true">—</span>,
    },
    {
      id: "kind",
      header: t("clients:kinds.column"),
      width: COLS.kind,
      cell: (row) => (
        <>
          <RelationTag kind={relationOf(row)} />
        </>
      ),
    },
    {
      id: "requests",
      header: t("clients:columns.requests"),
      width: COLS.requests,
      numeric: true,
      cell: (row) => (isPartnerOnly(row) ? "—" : row.open_requests),
    },
    {
      id: "erp",
      header: t("clients:columns.erp"),
      width: COLS.erp,
      cell: (row) => (
        <>
          <StateTag row={row} terms={termsOf.get(String(-row.id))} />
        </>
      ),
    },
    {
      id: "last",
      header: t("clients:columns.last"),
      width: COLS.last,
      cell: (row) => (
        <>
          <Activity row={row} />
        </>
      ),
    },
  ];
  return (
    <div className="pf-crm">
      <PageHeader
        title={title}
        extra={
          canEdit(me, "erp.stock") ? (
            <Button
              onClick={() => {
                setAddingPartner(true);
              }}
            >
              {t("clients:addPartner")}
            </Button>
          ) : undefined
        }
      />
      <div className="pf-crm-controls">
        <Segmented
          aria-label={t("clients:kinds.filter")}
          value={kind}
          options={shownKinds.map((value) => ({ value, label: kindLabel(value) }))}
          onChange={(value) => {
            change({ kind: value === "all" ? null : value });
          }}
        />
        {queue ? null : (
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
        )}
      </div>
      {kind === "applications" ? <PartnerApplicationsPanel /> : null}
      {kind === "bank_changes" ? <BankChangesPanel /> : null}
      {queue ? null : (
        <Card styles={{ body: { padding: 0 } }}>
          <QueryState query={seesClients ? list : partnersOnly} labels={labels} rows={20}>
            {(data) =>
              rowsOf(data.items).length === 0 ? (
                <EmptyState
                  title={t(q ? "clients:empty.filteredTitle" : "clients:empty.title")}
                  text={t(q ? "clients:empty.filteredText" : "clients:empty.text")}
                />
              ) : mobile ? (
                <ul className="pf-crm-list" aria-label={t("clients:listLabel")}>
                  {rowsOf(data.items).map((row) => (
                    <li key={row.id} className="pf-crm-item" data-selected={isOpen(row)}>
                      <div className="pf-crm-item-head">
                        <RelationTag kind={relationOf(row)} />
                        <StateTag row={row} terms={termsOf.get(String(-row.id))} />
                      </div>
                      <NameLink row={row} params={params} selected={isOpen(row)} />
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
                <DataTable
                  tableId="crm.clients"
                  caption={t("clients:caption")}
                  scrollLabel={t("clients:tableScroll")}
                  className="pf-crm-table"
                  flexMin={240}
                  columns={columns}
                  rows={rowsOf(data.items)}
                  rowKey={(row) => String(row.id)}
                  rowAttrs={(row) => ({
                    "data-selected": isOpen(row),
                  })}
                />
              )
            }
          </QueryState>
        </Card>
      )}
      {partner !== null ? (
        <Sheet label={t("clients:card.partnerLabel")} onClose={close}>
          <PartnerCard key={partner} id={partner} />
        </Sheet>
      ) : null}
      {addingPartner ? (
        <SupplierForm
          onClose={() => {
            setAddingPartner(false);
          }}
          onSaved={(saved) => {
            setAddingPartner(false);
            change({
              partner: saved.id,
              panel: mobile ? null : "open",
              tab: mobile ? null : "card",
            });
          }}
        />
      ) : null}
      {newRequest ? (
        <Sheet label={t("request:title")} onClose={close}>
          <CreateRequest key="create-new" lead={null} clientId={null} onCancel={close} />
        </Sheet>
      ) : null}
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
            <>
              {sameCompanyPartner ? (
                <p>
                  <Link
                    className="pf-crm-link pf-focusable"
                    to={`/crm/clients${withParams(params, {
                      client: null,
                      partner: sameCompanyPartner.id,
                    })}`}
                  >
                    {t("clients:card.openPartner")}
                  </Link>
                </p>
              ) : null}
              <ClientPanel key={selected} id={selected} onClose={close} />
            </>
          )}
        </Sheet>
      ) : null}
    </div>
  );
}
