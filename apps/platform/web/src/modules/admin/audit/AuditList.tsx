import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { actionLabel } from "../../../entities/audit/labels";
import type { AuditEntry } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { actorText, entityText } from "./describe";

import "./audit.css";
import { RegistryTable, type RegistryPagination } from "../../../shared/ui/RegistryTable";
import type { ReactNode } from "react";

export interface AuditListProps {
  items: readonly AuditEntry[];
  selectedId: string | null;
  /** Адрес записи: `?entry=<id>&panel=open` */
  hrefOf: (id: string) => string;
  names: ReadonlyMap<string, string>;
  /** Блок уже таблицы: строки списком, без колонок */
  compact: boolean;
  /** Рамка списка (RegistryTable): состояния и подвал */
  loading: boolean;
  error: ReactNode;
  empty: ReactNode;
  busy: boolean;
  resetKey: string;
  toolbar: ReactNode;
  pagination: RegistryPagination;
}

/** Журнал: таблица на широком экране, список строк на узком. Действие — ссылка, открывает запись в боковом окне. */
export function AuditList({
  items,
  selectedId,
  hrefOf,
  names,
  compact,
  loading,
  error,
  empty,
  busy,
  resetKey,
  toolbar,
  pagination,
}: AuditListProps) {
  const { t } = useTranslation("audit");
  const format = useFormat();
  const link = (entry: AuditEntry) => {
    const action = actionLabel(t, entry.action);
    return (
      <Link
        to={hrefOf(entry.id)}
        className="pf-audit-link pf-focusable"
        aria-current={entry.id === selectedId ? "true" : undefined}
        aria-label={t("open", { action, when: format.date(entry.at, "datetime") })}
      >
        {action}
      </Link>
    );
  };

  const list = compact ? (
    <ul className="pf-list" aria-label={t("listLabel")}>
      {items.map((entry) => (
        <li
          key={entry.id}
          className={`pf-audit-row${entry.id === selectedId ? " pf-audit-row-selected" : ""}`}
        >
          {link(entry)}
          <span className="pf-hint">
            {format.date(entry.at, "datetime")} · {actorText(t, entry, names)}
          </span>
          <span className="pf-hint">{entityText(t, entry, names)}</span>
        </li>
      ))}
    </ul>
  ) : undefined;

  return (
    <RegistryTable<AuditEntry>
      tableId="admin.audit"
      caption={t("listLabel")}
      scrollLabel={t("listLabel")}
      rows={items}
      rowKey={(row) => row.id}
      selectedKey={selectedId}
      loading={loading}
      skeletonRows={pagination.pageSize}
      error={error}
      empty={empty}
      busy={busy}
      resetKey={resetKey}
      toolbar={toolbar}
      list={list}
      pagination={pagination}
      columns={[
        {
          id: "when",
          header: t("columns.when"),
          width: 172,
          cell: (entry) => <span className="pf-num">{format.date(entry.at, "datetime")}</span>,
        },
        {
          id: "actor",
          header: t("columns.actor"),
          width: 220,
          cell: (entry) => actorText(t, entry, names),
        },
        {
          id: "action",
          header: t("columns.action"),
          width: 352,
          cell: (entry) => link(entry),
        },
        {
          id: "entity",
          header: t("columns.entity"),
          width: 308,
          cell: (entry) => entityText(t, entry, names),
        },
      ]}
    />
  );
}
