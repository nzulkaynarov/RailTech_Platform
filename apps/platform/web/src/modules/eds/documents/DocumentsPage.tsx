import { Button, Card, Select, Segmented, Tabs } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import type {
  EdsDocumentRow,
  EdsRegistryKind,
  ListEdsDocumentsParams,
} from "../../../shared/api/generated/model";
import { useListEdsDocuments } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DocNumber } from "../../../shared/ui/DocNumber";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PlusIcon } from "../../../shared/ui/icons";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { DocumentSheet } from "./DocumentSheet";
import { parseDocumentId, withParams } from "./params";
import { DocumentStatusTag } from "./status";

import "./documents.css";

const PAGE_SIZE = 25;
const KIND_TABS = ["all", "memo", "application", "report", "letters", "quote"] as const;
type KindTab = (typeof KIND_TABS)[number];
const TAB_KINDS: Record<Exclude<KindTab, "all">, EdsRegistryKind[]> = {
  memo: ["memo"],
  application: ["application"],
  report: ["report"],
  letters: ["letter_in", "letter_out"],
  quote: ["quote"],
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
/** Куда ведут строки реестра, которые не открываются в этом окне: пункт меню EDS и его ключ в `modules` */
const SECTION_OF: Partial<Record<EdsRegistryKind, { key: string; path: string }>> = {
  letter_in: { key: "inbox", path: "/eds/inbox" },
  quote: { key: "drafts", path: "/eds/drafts" },
};

type Scope = "mine" | "all";

function tabOf(value: string | null, scope: Scope): KindTab {
  const found = KIND_TABS.find((tab) => tab === value);
  if (found === undefined || (found === "quote" && scope === "mine")) return "all";
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
  const section = SECTION_OF[row.kind];
  if (!section) return null;
  const label = t(`modules:eds.sections.${section.key}`);
  return (
    <Link
      className="pf-docs-link pf-focusable"
      to={section.path}
      aria-label={t("documents:list.inSectionLabel", { section: label, subject: row.subject })}
    >
      {t("documents:list.inSection", { section: label })}
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
  if (!row.openable) return <span>{row.subject}</span>;
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

function Amount({ row }: { row: EdsDocumentRow }) {
  if (!row.amount) return <span aria-hidden="true">—</span>;
  return (
    <MoneyText
      value={row.amount.amount}
      {...(row.amount.currency === "UZS" ? {} : { currency: row.amount.currency })}
    />
  );
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
  return (
    <ScrollRegion label={t("list.tableScroll")}>
      <table className="pf-docs-table">
        <caption className="pf-sr-only">{t("list.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("list.columns.number")}</th>
            <th scope="col">{t("list.columns.subject")}</th>
            <th scope="col">{t("list.columns.kind")}</th>
            <th scope="col">{t("list.columns.status")}</th>
            <th scope="col" className="num">
              {t("list.columns.amount")}
            </th>
            <th scope="col">{t("list.columns.due")}</th>
            {scope === "all" ? <th scope="col">{t("list.columns.responsible")}</th> : null}
            <th scope="col">{t("list.columns.created")}</th>
            <th scope="col">{t("list.columns.action")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={`${row.kind}-${row.id}`} data-selected={selected === row.id}>
              <td>
                {row.number ? (
                  <DocNumber number={row.number} />
                ) : (
                  <span className="pf-hint">{t("list.noNumber")}</span>
                )}
              </td>
              <td className="pf-docs-subject">
                <SubjectCell row={row} params={params} selected={selected === row.id} />
              </td>
              <td>{t(`kinds.${row.kind}`)}</td>
              <td>
                <DocumentStatusTag kind={row.kind} status={row.status} />
              </td>
              <td className="num">
                <Amount row={row} />
              </td>
              <td>{row.due_date ? date(row.due_date) : <span aria-hidden="true">—</span>}</td>
              {scope === "all" ? <td>{row.author?.full_name ?? "—"}</td> : null}
              <td>{date(row.created_at)}</td>
              <td>
                <RowAction row={row} own={isOwn(row)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
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
            <DocumentStatusTag kind={row.kind} status={row.status} />
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
            {scope === "all" && row.author ? <span>{row.author.full_name}</span> : null}
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
  const title = t("modules:eds.sections.documents");
  useDocumentTitle(title);

  const canViewAll = canSee(me, { anyOf: ["eds.inbox", "eds.projects", "eds.payments"] });
  // Реестр компании — по умолчанию у ролей, которым он открыт; остальным — только «Мои».
  const scope: Scope = canViewAll && params.get("scope") !== "mine" ? "all" : "mine";
  const lettersAllowed = canSee(me, { resource: "eds.inbox" });
  const askedTab = tabOf(params.get("kind"), scope);
  const tab = askedTab === "letters" && !lettersAllowed ? "all" : askedTab;
  const status = params.get("status") ?? "";
  const docId = parseDocumentId(params.get("doc"));

  // Страницы списка идут курсором: стек пройденных курсоров; смена условий возвращает на первую страницу.
  const filterKey = `${scope}|${tab}|${status}`;
  const [paging, setPaging] = useState<{ key: string; stack: string[] }>({ key: "", stack: [] });
  const cursors = paging.key === filterKey ? paging.stack : [];
  const setCursors = (change: (stack: string[]) => string[]) => {
    setPaging({ key: filterKey, stack: change(cursors) });
  };
  const cursor = cursors[cursors.length - 1];

  const query: ListEdsDocumentsParams = useMemo(
    () => ({
      scope,
      ...(tab === "all" ? {} : { kind: TAB_KINDS[tab] }),
      ...(status ? { status: [status] } : {}),
      limit: PAGE_SIZE,
      ...(cursor ? { cursor } : {}),
    }),
    [scope, tab, status, cursor],
  );
  const list = useListEdsDocuments(query);

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

  const statuses = [
    ...DOCUMENT_STATUSES,
    ...(scope === "all" ? REGISTRY_STATUSES : []),
  ] as readonly string[];
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

  // «КП» — только в реестре компании; «Письма» — у ролей с чтением входящих (`eds.inbox`), остальным реестр писем не отдаётся.
  const kindTabs = KIND_TABS.filter(
    (k) => (k !== "quote" || scope === "all") && (k !== "letters" || lettersAllowed),
  );

  const body = (
    <QueryState query={list} labels={labels}>
      {(data) =>
        data.items.length === 0 ? (
          <EmptyState
            title={t(
              filtered
                ? "documents:list.empty.filteredTitle"
                : scope === "all"
                  ? "documents:list.empty.allTitle"
                  : "documents:list.empty.mineTitle",
            )}
            text={t(
              filtered
                ? "documents:list.empty.filteredText"
                : scope === "all"
                  ? "documents:list.empty.allText"
                  : "documents:list.empty.mineText",
            )}
            action={
              canEdit(me, "eds.memo.create") ? (
                <LinkButton type="primary" to="/eds/new">
                  {t("modules:eds.action")}
                </LinkButton>
              ) : undefined
            }
          />
        ) : (
          <>
            {mobile ? (
              <DocumentsList items={data.items} scope={scope} selected={docId} params={params} />
            ) : (
              <DocumentsTable items={data.items} scope={scope} selected={docId} params={params} />
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

  return (
    <div className="pf-docs">
      <PageHeader
        title={title}
        subtitle={t(scope === "all" ? "documents:list.subtitleAll" : "documents:list.subtitle")}
        extra={
          canEdit(me, "eds.memo.create") ? (
            <LinkButton type="primary" icon={<PlusIcon />} to="/eds/new">
              {t("modules:eds.action")}
            </LinkButton>
          ) : null
        }
      />
      <div className="pf-docs-controls">
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
          <div className="pf-docs-filter">
            <label htmlFor="pf-docs-kind">{t("documents:list.tabs.label")}</label>
            <Select
              id="pf-docs-kind"
              style={{ minWidth: 180 }}
              value={tab}
              options={kindTabs.map((key) => ({
                value: key,
                label: t(`documents:list.tabs.${key}`),
              }))}
              onChange={(key) => {
                setFilter({ kind: key === "all" ? null : key });
              }}
            />
          </div>
        ) : null}
        <div className="pf-docs-filter">
          <label htmlFor="pf-docs-status">{t("documents:list.status.label")}</label>
          <Select
            id="pf-docs-status"
            style={{ minWidth: 220 }}
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
        </div>
      </div>
      <Card styles={{ body: { padding: 0 } }}>
        {mobile ? (
          body
        ) : (
          <Tabs
            aria-label={t("documents:list.tabs.label")}
            activeKey={tab}
            onChange={(key) => {
              setFilter({ kind: key === "all" ? null : key });
            }}
            tabBarStyle={{ margin: 0, padding: "0 16px" }}
            items={kindTabs.map((key) => ({
              key,
              label: t(`documents:list.tabs.${key}`),
              children: key === tab ? body : null,
            }))}
          />
        )}
      </Card>
      {docId ? <DocumentSheet id={docId} /> : null}
    </div>
  );
}
