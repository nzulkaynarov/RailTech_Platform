import { Table } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { actionLabel } from "../../../entities/audit/labels";
import type { AuditEntry } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { actorText, entityText } from "./describe";

import "./audit.css";

export interface AuditListProps {
  items: readonly AuditEntry[];
  selectedId: string | null;
  /** Адрес записи: `?entry=<id>&panel=open` */
  hrefOf: (id: string) => string;
  names: ReadonlyMap<string, string>;
  /** Блок уже таблицы: строки списком, без колонок */
  compact: boolean;
}

/** Журнал: таблица на широком экране, список строк на узком. Действие — ссылка, открывает запись в боковом окне. */
export function AuditList({ items, selectedId, hrefOf, names, compact }: AuditListProps) {
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

  if (compact) {
    return (
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
    );
  }

  return (
    <Table<AuditEntry>
      rowKey="id"
      dataSource={[...items]}
      pagination={false}
      tableLayout="fixed"
      aria-label={t("listLabel")}
      rowClassName={(entry) => (entry.id === selectedId ? "pf-audit-table-row-selected" : "")}
      columns={[
        {
          title: t("columns.when"),
          key: "when",
          width: 172,
          render: (_, entry) => <span className="pf-num">{format.date(entry.at, "datetime")}</span>,
        },
        {
          title: t("columns.actor"),
          key: "actor",
          width: "20%",
          render: (_, entry) => actorText(t, entry, names),
        },
        {
          title: t("columns.action"),
          key: "action",
          width: "32%",
          render: (_, entry) => link(entry),
        },
        {
          title: t("columns.entity"),
          key: "entity",
          width: "28%",
          render: (_, entry) => entityText(t, entry, names),
        },
      ]}
    />
  );
}
