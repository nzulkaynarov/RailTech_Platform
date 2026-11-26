import { Button, Card, Select, Segmented } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import type {
  EdsDocumentRow,
  EdsRegistryKind,
  ListEdsDocumentsParams,
  Me,
} from "../../../shared/api/generated/model";
import { useListEdsDocuments } from "../../../shared/api/generated/platform-bff";
import { quotePath } from "../drafts/api";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useShownValue } from "../../../shared/lib/useShownKey";
import { useFormat } from "../../../shared/lib/useFormat";
import { DocNumber } from "../../../shared/ui/DocNumber";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { useSortParam } from "../../../shared/ui/DataTable/sort";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { TabsBar } from "../../../shared/ui/TabsBar";
import { DocumentSheet } from "./DocumentSheet";
import { parseDocumentId, withParams } from "./params";
import { DocumentStatusTag } from "./status";
import { StatusTag } from "../../../shared/ui/StatusTag";

import "./documents.css";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { PersonRefCell } from "../../PersonRefCell";
import { PageFrame } from "../../../shared/ui/PageFrame";

const PAGE_SIZE = 25;

/** Порядок щелчком по шапке (Х-15б): ключи те же, что принимает BFF `sort` (белый список там и в EDS) */
const DOCUMENT_SORT_KEYS = ["number", "subject", "status", "amount", "created"] as const;
/**
 * Ширины колонок по типу (platform-frontend.md §4.2): номер (тип документа — второй строкой, как в «На согласовании»),
 * тема (гибкая), статус, сумма, срок, [ответственный — в реестре «Все»], создан, действие. На 1440 с открытым подменю —
 * без прокрутки вбок (T1).
 */
const colsOf = (scope: Scope) => ({
  number: 148,
  status: scope === "all" ? 172 : 196,
  amount: 144,
  due: 104,
  responsible: 136,
  created: 104,
  action: 128,
});
const KIND_TABS = [
  "all",
  "memo",
  "application",
  "report",
  "letters",
  "quote",
  "contract",
  "invoice",
  "act",
] as const;
/** Вкладки реестра компании: КП и документы проектов видны только в «Все документы» */
const REGISTRY_TABS: readonly KindTab[] = ["quote", "contract", "invoice", "act"];
type KindTab = (typeof KIND_TABS)[number];
const TAB_KINDS: Record<Exclude<KindTab, "all">, EdsRegistryKind[]> = {
  memo: ["memo"],
  application: ["application"],
  report: ["report"],
  letters: ["letter_in", "letter_out"],
  quote: ["quote"],
  contract: ["contract"],
  invoice: ["invoice"],
  act: ["act"],
};
/** Статусы фильтра: документы всегда; входящие письма и КП — когда открыт реестр */
const DOCUMENT_STATUSES = [
  "draft",
  "on_approval",
  "returned",
  "approved",
  "rejected",
  "to_accountant",
  "paid",
  "sent",
] as const;
const REGISTRY_STATUSES = ["awaiting_resolution", "resolved", "open"] as const;

/** Пункты меню «Документов» поверх одного реестра: что показывает каждый */
const BOXES = ["outgoing", "internal", "archive"] as const;
type Box = (typeof BOXES)[number];
const BOX_TABS: Record<Box, readonly KindTab[]> = {
  outgoing: ["all", "letters", "quote", "contract", "invoice", "act"],
  internal: ["all", "memo", "application", "report"],
  archive: KIND_TABS,
};
/**
 * Стадия ящика (план 2026-11-12 п. 0.9, FR-5): «Исходящие» и «Внутренние» — документы, которые ещё ждут чьего-то действия,
 * в том числе контрагента; «Архив» — путь завершён. Какие статусы конечные у каждого вида, решает EDS (`stage`).
 */
const BOX_STAGE: Record<Box, "open" | "done"> = {
  outgoing: "open",
  internal: "open",
  archive: "done",
};

function boxOf(value: string | null): Box | undefined {
  return BOXES.find((box) => box === value);
}

/** Виды документов для запроса: вкладка сужает ящик, в «Исходящих» письма только отправленные */
function kindsOf(tab: KindTab, box: Box | undefined): EdsRegistryKind[] | undefined {
  if (tab !== "all")
    return box === "outgoing" && tab === "letters" ? ["letter_out"] : TAB_KINDS[tab];
  if (box === undefined || box === "archive") return undefined;
  return BOX_TABS[box].flatMap((key) => (key === "all" ? [] : (kindsOf(key, box) ?? [])));
}
const BOX_NAV: Record<Box, string> = {
  outgoing: "outbox",
  internal: "internal",
  archive: "archive",
};

const INBOX_ACCESS = { anyOf: ["eds.inbox", "eds.inbox.register"] } as const;

/**
 * Куда ведёт строка, которая не открывается в этом окне (ДОК-8: строки без просмотра нет): входящее письмо — в само
 * письмо, КП — в карточку одобрения, договор, счёт и акт проекта — в карточку проекта. `null` — раздел сотруднику закрыт.
 */
function pagePath(row: EdsDocumentRow, me: Me): string | null {
  if (row.kind === "letter_in")
    // Номер в адресе — как у ссылок между письмами: в цепочке навигации «ВХ-104/26», а не идентификатор.
    return canSee(me, INBOX_ACCESS)
      ? `/eds/inbox/${encodeURIComponent(row.number ?? row.id)}`
      : null;
  if (row.project_ref && canSee(me, { resource: "eds.projects" }))
    return `/eds/projects/${encodeURIComponent(row.project_ref)}`;
  if (row.kind === "quote") return quotePath(row.id);
  return null;
}

type Scope = "mine" | "all";

function tabOf(value: string | null, scope: Scope): KindTab {
  const found = KIND_TABS.find((tab) => tab === value);
  if (found === undefined || (found !== "all" && REGISTRY_TABS.includes(found) && scope === "mine"))
    return "all";
  return found;
}

/** Строка — документ самого сотрудника: в «Мои» все такие, в реестре — по автору (`crm_user_id` = id сотрудника). */
function useIsOwn(scope: Scope): (row: EdsDocumentRow) => boolean {
  const { me } = useAuth();
  return (row) =>
    scope === "mine" || (row.author !== null && String(row.author.crm_user_id) === me.id);
}

function RowAction({ row, own }: { row: EdsDocumentRow; own: boolean }) {
  const { t } = useTranslation(["documents", "modules"]);
  const { me } = useAuth();
  if (row.openable) {
    // «Продолжить» — только у своих черновиков и возвращённых: чужой документ править нельзя (EDS ответит 403).
    if (!own || (row.status !== "draft" && row.status !== "returned")) return null;
    return (
      <LinkButton
        size="small"
        to={`/eds/new?draft=${row.id}`}
        aria-label={t("documents:list.continueLabel", { subject: row.subject })}
      >
        {t("documents:list.continue")}
      </LinkButton>
    );
  }
  const to = pagePath(row, me);
  if (to === null) return null;
  // Договор, счёт и акт проекта (проекция ERP) ведут в карточку проекта; КП — в карточку одобрения (`/eds/drafts/<id>`,
  // раздела «КП на одобрение» в меню нет, FR-5); входящее письмо — в само письмо, а не в раздел (ДОК-8).
  const key =
    row.kind === "letter_in" ? "openLetter" : row.kind === "quote" ? "openQuote" : "inProject";
  return (
    <Link
      className="pf-docs-link pf-focusable"
      to={to}
      aria-label={t(`documents:list.${key}Label`, { subject: row.subject })}
    >
      {t(`documents:list.${key}`)}
    </Link>
  );
}

function SubjectCell({
  row,
  params,
  selected,
}: {
  row: EdsDocumentRow;
  params: URLSearchParams;
  selected: boolean;
}) {
  const { t } = useTranslation("documents");
  // На телефоне документ открывает собственный лист, окно каркаса (`panel=open`) не нужно.
  const { mobile } = useViewport();
  const { me } = useAuth();
  if (!row.openable) {
    // Тема — ссылка на сам документ у любого вида (ДОК-8); нет доступа к его разделу — текст.
    const to = pagePath(row, me);
    if (to === null) return <span>{row.subject}</span>;
    return (
      <Link
        className="pf-docs-link pf-focusable"
        to={to}
        aria-label={t("list.open", { subject: row.subject })}
      >
        {row.subject}
      </Link>
    );
  }
  return (
    <Link
      className="pf-docs-link pf-focusable"
      to={withParams(params, { doc: row.id, panel: mobile ? null : "open" })}
      aria-label={t("list.open", { subject: row.subject })}
      aria-current={selected ? "true" : undefined}
    >
      {row.subject}
    </Link>
  );
}

/** Статус строки; у письма, которое не ушло адресату, — метка исхода: поэтому оно в «Исходящих», а не в «Архиве» (СЦ-1). */
function RowStatus({ row }: { row: EdsDocumentRow }) {
  const { t } = useTranslation("documents");
  return (
    <>
      <DocumentStatusTag
        kind={row.kind}
        status={row.status}
        awaitingSignature={row.awaiting_signature}
      />
      {row.undelivered ? <StatusTag tone="red">{t("panel.mailFailed")}</StatusTag> : null}
      {row.awaiting_signature && row.signer ? (
        <div className="pf-hint">{t("list.onSigningAt", { name: row.signer.full_name })}</div>
      ) : null}
    </>
  );
}

function Amount({ row }: { row: EdsDocumentRow }) {
  if (!row.amount) return <span aria-hidden="true">—</span>;
  return <MoneyText value={row.amount.amount} currency={row.amount.currency} />;
}

function DocumentsTable({
  items,
  scope,
  selected,
  params,
}: {
  items: readonly EdsDocumentRow[];
  scope: Scope;
  selected: string | null;
  params: URLSearchParams;
}) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  const isOwn = useIsOwn(scope);
  const widths = colsOf(scope);
  const all = scope === "all";
  // Ширины по типу — те же `colsOf` (T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<EdsDocumentRow>[] = [
    {
      id: "number",
      header: t("list.columns.number"),
      sortKey: "number",
      width: widths.number,
      cell: (row) => (
        <>
          {row.number ? (
            <DocNumber number={row.number} />
          ) : (
            <span className="pf-hint">
              {t(row.kind === "letter_out" ? "list.noNumberSigning" : "list.noNumber")}
            </span>
          )}
          <div className="pf-hint pf-ell" title={t(`kinds.${row.kind}`)}>
            <span className="pf-sr-only">{t("list.columns.kind")}: </span>
            {t(`kinds.${row.kind}`)}
          </div>
        </>
      ),
    },
    {
      id: "subject",
      header: t("list.columns.subject"),
      sortKey: "subject",
      width: null,
      cellClassName: "pf-docs-subject",
      cell: (row) => <SubjectCell row={row} params={params} selected={selected === row.id} />,
    },
    {
      id: "status",
      header: t("list.columns.status"),
      sortKey: "status",
      width: widths.status,
      cell: (row) => <RowStatus row={row} />,
    },
    {
      id: "amount",
      header: t("list.columns.amount"),
      sortKey: "amount",
      width: widths.amount,
      numeric: true,
      cell: (row) => <Amount row={row} />,
    },
    {
      id: "due",
      header: t("list.columns.due"),
      width: widths.due,
      cellClassName: "pf-num",
      cell: (row) => (row.due_date ? date(row.due_date) : <span aria-hidden="true">—</span>),
    },
    ...(all
      ? [
          {
            id: "responsible",
            header: t("list.columns.responsible"),
            width: widths.responsible,
            cellClassName: "pf-ell",
            cellTitle: (row: EdsDocumentRow) => row.author?.full_name ?? undefined,
            cell: (row: EdsDocumentRow) =>
              row.author ? (
                <PersonRefCell
                  person={{ id: String(row.author.crm_user_id), name: row.author.full_name }}
                  caption={null}
                />
              ) : (
                "—"
              ),
          },
        ]
      : []),
    {
      id: "created",
      header: t("list.columns.created"),
      sortKey: "created",
      width: widths.created,
      cellClassName: "pf-num",
      cell: (row) => date(row.created_at),
    },
    {
      id: "action",
      header: t("list.columns.action"),
      width: widths.action,
      cell: (row) => <RowAction row={row} own={isOwn(row)} />,
    },
  ];
  return (
    <DataTable
      tableId="eds.documents"
      caption={t("list.caption")}
      scrollLabel={t("list.tableScroll")}
      className="pf-docs-table"
      columns={columns}
      sortMode="server"
      rows={items}
      rowKey={(row) => `${row.kind}-${row.id}`}
      rowAttrs={(row) => ({ "data-selected": selected === row.id })}
    />
  );
}

function DocumentsList({
  items,
  scope,
  selected,
  params,
}: {
  items: readonly EdsDocumentRow[];
  scope: Scope;
  selected: string | null;
  params: URLSearchParams;
}) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  const isOwn = useIsOwn(scope);
  return (
    <ul className="pf-docs-list" aria-label={t("list.listLabel")}>
      {items.map((row) => (
        <li
          key={`${row.kind}-${row.id}`}
          className="pf-docs-item"
          data-selected={selected === row.id}
        >
          <div className="pf-docs-item-head">
            <RowStatus row={row} />
            {row.number ? <DocNumber number={row.number} /> : null}
          </div>
          <div className="pf-docs-subject">
            <SubjectCell row={row} params={params} selected={selected === row.id} />
          </div>
          <div className="pf-docs-item-meta">
            <span>{t(`kinds.${row.kind}`)}</span>
            {row.amount ? <Amount row={row} /> : null}
            {row.due_date ? (
              <span>
                {t("list.columns.due")}: {date(row.due_date)}
              </span>
            ) : null}
            {scope === "all" && row.author ? (
              <PersonRefCell
                person={{ id: String(row.author.crm_user_id), name: row.author.full_name }}
                caption={null}
              />
            ) : null}
            <span>{date(row.created_at)}</span>
          </div>
          <div>
            <RowAction row={row} own={isOwn(row)} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * EDS · «Мои документы» и реестр «Все документы» (SPEC-v3 §7.3, D1-5): вкладки по типу, фильтр по статусу, переключатель
 * «Мои / Все» (реестр компании — у ролей с чтением входящих, проектов или платежей), курсорная пагинация. Клик по документу —
 * карточка в боковом окне (на телефоне — лист на весь экран), черновик — «Продолжить».
 */
export function DocumentsPage() {
  const { t } = useTranslation(["documents", "modules"]);
  const { me } = useAuth();
  const { mobile } = useViewport();
  const [params, setParams] = useSearchParams();
  const box = boxOf(params.get("box"));
  const title = t(box ? `modules:eds.nav.${BOX_NAV[box]}` : "modules:eds.sections.documents");
  useDocumentTitle(title);

  const canViewAll = canSee(me, { anyOf: ["eds.inbox", "eds.projects", "eds.payments"] });
  // Реестр компании — по умолчанию у ролей, которым он открыт; остальным — только «Мои».
  const scope: Scope = canViewAll && params.get("scope") !== "mine" ? "all" : "mine";
  const lettersAllowed = canSee(me, { resource: "eds.inbox" });
  const askedTab = tabOf(params.get("kind"), scope);
  const allowedTab = askedTab === "letters" && !lettersAllowed ? "all" : askedTab;
  const tab = box && !BOX_TABS[box].includes(allowedTab) ? "all" : allowedTab;
  const status = params.get("status") ?? "";
  const docId = parseDocumentId(params.get("doc"));

  // Страницы списка идут курсором: стек пройденных курсоров; смена условий возвращает на первую страницу.
  // Порядок щелчком по шапке (Х-15б) — часть условий: курсор привязан к порядку, смена порядка начинает с первой страницы.
  const sort = useSortParam(DOCUMENT_SORT_KEYS);
  const filterKey = `${box ?? ""}|${scope}|${tab}|${status}|${sort ?? ""}`;
  const [paging, setPaging] = useState<{ key: string; stack: string[] }>({ key: "", stack: [] });
  const cursors = paging.key === filterKey ? paging.stack : [];
  const setCursors = (change: (stack: string[]) => string[]) => {
    setPaging({ key: filterKey, stack: change(cursors) });
  };
  const cursor = cursors[cursors.length - 1];

  const kinds = useMemo(() => kindsOf(tab, box), [tab, box]);
  const statusFilter = useMemo<string[] | undefined>(
    () => (status ? [status] : undefined),
    [status],
  );
  const stage = box ? BOX_STAGE[box] : undefined;
  const query: ListEdsDocumentsParams = useMemo(
    () => ({
      scope,
      ...(kinds ? { kind: kinds } : {}),
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(stage ? { stage } : {}),
      ...(sort ? { sort } : {}),
      limit: PAGE_SIZE,
      ...(cursor ? { cursor } : {}),
    }),
    [scope, kinds, statusFilter, stage, sort, cursor],
  );
  const list = useListEdsDocuments(query);
  // Колонки, подписи и подзаголовок — по реестру, к которому относятся строки на экране (UX-1c, S8)
  const shownScope = useShownValue(scope, list.isPlaceholderData);

  const setFilter = (changes: Record<string, string | null>) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null) next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  };

  const allStatuses = [
    ...DOCUMENT_STATUSES,
    ...(scope === "all" ? REGISTRY_STATUSES : []),
  ] as readonly string[];
  const statuses = allStatuses;
  const filtered = tab !== "all" || status !== "";

  const labels = {
    retry: t("documents:list.retry"),
    loadError: {
      title: t("documents:list.loadError.title"),
      text: t("documents:list.loadError.text"),
    },
    unavailable: {
      title: t("documents:list.unavailable.title"),
      text: t("documents:list.unavailable.text"),
    },
    forbidden: {
      title: t("documents:list.forbidden.title"),
      text: t("documents:list.forbidden.text"),
    },
  };

  const kindTabs = KIND_TABS.filter(
    (k) =>
      (!REGISTRY_TABS.includes(k) || scope === "all") &&
      (k !== "letters" || lettersAllowed) &&
      (!box || BOX_TABS[box].includes(k)),
  );

  const body = (
    <QueryState query={list} labels={labels} rows={PAGE_SIZE}>
      {(data) =>
        data.items.length === 0 ? (
          <EmptyState
            title={t(
              filtered
                ? "documents:list.empty.filteredTitle"
                : shownScope === "all"
                  ? "documents:list.empty.allTitle"
                  : "documents:list.empty.mineTitle",
            )}
            text={t(
              filtered
                ? "documents:list.empty.filteredText"
                : shownScope === "all"
                  ? "documents:list.empty.allText"
                  : "documents:list.empty.mineText",
            )}
          />
        ) : (
          <>
            {mobile ? (
              <DocumentsList
                items={data.items}
                scope={shownScope}
                selected={docId}
                params={params}
              />
            ) : (
              <DocumentsTable
                items={data.items}
                scope={shownScope}
                selected={docId}
                params={params}
              />
            )}
            {cursors.length > 0 || data.next_cursor ? (
              <nav className="pf-docs-pager" aria-label={t("documents:list.paging.label")}>
                <Button
                  disabled={cursors.length === 0}
                  onClick={() => {
                    setCursors((stack) => stack.slice(0, -1));
                  }}
                >
                  {t("documents:list.paging.prev")}
                </Button>
                <span className="pf-hint">
                  {t("documents:list.paging.page", { page: cursors.length + 1 })}
                </span>
                <Button
                  disabled={!data.next_cursor}
                  onClick={() => {
                    const next = data.next_cursor;
                    if (next) setCursors((stack) => [...stack, next]);
                  }}
                >
                  {t("documents:list.paging.next")}
                </Button>
              </nav>
            ) : null}
          </>
        )
      }
    </QueryState>
  );

  const filterBar = (
    <FilterBar tools>
      {canViewAll ? (
        <Segmented
          aria-label={t("documents:list.scope.label")}
          value={scope}
          options={[
            { value: "mine", label: t("documents:list.scope.mine") },
            { value: "all", label: t("documents:list.scope.all") },
          ]}
          onChange={(value) => {
            setFilter({ scope: value, kind: null, status: null, doc: null, panel: null });
          }}
        />
      ) : null}
      {mobile ? (
        <FilterField id="pf-docs-kind" label={t("documents:list.tabs.label")}>
          <Select
            id="pf-docs-kind"
            value={tab}
            options={kindTabs.map((key) => ({
              value: key,
              label: t(`documents:list.tabs.${key}`),
            }))}
            onChange={(key) => {
              setFilter({ kind: key === "all" ? null : key });
            }}
          />
        </FilterField>
      ) : null}
      <FilterField id="pf-docs-status" label={t("documents:list.status.label")} width={240}>
        <Select
          id="pf-docs-status"
          value={status}
          options={[
            { value: "", label: t("documents:list.status.any") },
            ...statuses.map((value) => ({
              value,
              label: t(`documents:status.filter.${value}`),
            })),
          ]}
          onChange={(value) => {
            setFilter({ status: value === "" ? null : value });
          }}
        />
      </FilterField>
    </FilterBar>
  );
  return (
    <PageFrame layout="registry">
      <div className="pf-docs">
        <PageHeader
          title={title}
          {...(canSee(me, { resource: "company.settings" })
            ? {
                // ЕВ-3а: «Шаблоны» ушли из меню «Документов» — вход отсюда и из «Настроек · Компания»
                extra: <Link to="/admin/templates">{t("modules:admin.templatesLink")}</Link>,
              }
            : {})}
        />
        {mobile ? (
          <>
            {filterBar}
            <Card styles={{ body: { padding: 0 } }}>{body}</Card>
          </>
        ) : (
          // Одна строка вкладок видов, под ней одна строка фильтров и рамка списка
          <TabsBar
            id="pf-docs-tabs"
            label={t("documents:list.tabs.label")}
            activeKey={tab}
            onChange={(key) => {
              setFilter({ kind: key === "all" ? null : key });
            }}
            items={kindTabs.map((key) => ({ key, label: t(`documents:list.tabs.${key}`) }))}
            stack
          >
            {filterBar}
            <Card styles={{ body: { padding: 0 } }}>{body}</Card>
          </TabsBar>
        )}
        {docId ? <DocumentSheet id={docId} /> : null}
      </div>
    </PageFrame>
  );
}
