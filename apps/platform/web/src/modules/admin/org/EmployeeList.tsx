import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Employee } from "../../../shared/api/generated/model";
import { PersonAvatar, PersonCell } from "../../../shared/ui/EntityCell";
import { AccessTags, EmployeeStatusTag, RoleTags } from "./EmployeeCells";
import { RegistryTable } from "../../../shared/ui/RegistryTable";

export interface EmployeeListProps {
  items: readonly Employee[];
  selectedId: string | null;
  /** Адрес карточки сотрудника: `?employee=<id>&panel=open` */
  hrefOf: (id: string) => string;
  /** Блок уже таблицы: строки списком, без колонок */
  compact: boolean;
  /** Рамка списка (RegistryTable): состояния и строка фильтров */
  loading: boolean;
  error: ReactNode;
  empty: ReactNode;
  toolbar: ReactNode;
}

function NameLink({
  employee,
  selected,
  href,
}: {
  employee: Employee;
  selected: boolean;
  href: string;
}) {
  const { t } = useTranslation("modules");
  return (
    <Link
      to={href}
      className="pf-org-name pf-focusable"
      aria-current={selected ? "true" : undefined}
      aria-label={t("admin.org.open", { name: employee.name })}
    >
      {employee.name}
    </Link>
  );
}

/** Сотрудники: таблица на широком экране, список строк на узком. Имя — ссылка, открывает карточку в боковом окне. */
export function EmployeeList({
  items,
  selectedId,
  hrefOf,
  compact,
  loading,
  error,
  empty,
  toolbar,
}: EmployeeListProps) {
  const { t } = useTranslation("modules");
  const label = t("admin.org.listLabel");

  const list = compact ? (
    <ul className="pf-list" aria-label={label}>
      {items.map((employee) => (
        <li
          key={employee.id}
          className={`pf-org-row${employee.id === selectedId ? " pf-org-row-selected" : ""}`}
        >
          <PersonAvatar name={employee.name} photoUrl={employee.avatar_url} size={32} />
          <div className="pf-org-row-body">
            <div className="pf-org-row-head">
              <NameLink
                employee={employee}
                selected={employee.id === selectedId}
                href={hrefOf(employee.id)}
              />
              <EmployeeStatusTag status={employee.status} />
            </div>
            <div className="pf-hint">
              {employee.position ?? t("admin.org.noPosition")} · {employee.email}
            </div>
            <RoleTags roles={employee.roles} />
            <AccessTags employee={employee} />
          </div>
        </li>
      ))}
    </ul>
  ) : undefined;

  return (
    <RegistryTable<Employee>
      tableId="admin.org.employees"
      caption={label}
      scrollLabel={label}
      rows={items}
      rowKey={(row) => row.id}
      selectedKey={selectedId}
      loading={loading}
      error={error}
      empty={empty}
      toolbar={toolbar}
      list={list}
      columns={[
        {
          id: "employee",
          header: t("admin.org.columns.employee"),
          width: 286,
          cell: (employee) => (
            <PersonCell
              name={employee.name}
              caption={employee.email}
              photoUrl={employee.avatar_url}
              size={32}
              title={
                <NameLink
                  employee={employee}
                  selected={employee.id === selectedId}
                  href={hrefOf(employee.id)}
                />
              }
            />
          ),
        },
        {
          id: "position",
          header: t("admin.org.columns.position"),
          width: 209,
          cell: (employee) =>
            employee.position ?? <span className="pf-hint">{t("admin.org.noPosition")}</span>,
        },
        {
          id: "roles",
          header: t("admin.org.columns.roles"),
          width: 209,
          cell: (employee) => <RoleTags roles={employee.roles} />,
        },
        {
          id: "access",
          header: t("admin.org.columns.access"),
          width: 220,
          cell: (employee) => <AccessTags employee={employee} />,
        },
        {
          id: "status",
          header: t("admin.org.columns.status"),
          width: 176,
          cell: (employee) => <EmployeeStatusTag status={employee.status} />,
        },
      ]}
    />
  );
}
