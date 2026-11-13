import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Employee } from "../../../shared/api/generated/model";
import { AccessTags, EmployeeStatusTag, Initials, RoleTags } from "./EmployeeCells";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";

export interface EmployeeListProps {
  items: readonly Employee[];
  selectedId: string | null;
  /** Адрес карточки сотрудника: `?employee=<id>&panel=open` */
  hrefOf: (id: string) => string;
  /** Блок уже таблицы: строки списком, без колонок */
  compact: boolean;
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
export function EmployeeList({ items, selectedId, hrefOf, compact }: EmployeeListProps) {
  const { t } = useTranslation("modules");
  const label = t("admin.org.listLabel");

  if (compact) {
    return (
      <ul className="pf-list" aria-label={label}>
        {items.map((employee) => (
          <li
            key={employee.id}
            className={`pf-org-row${employee.id === selectedId ? " pf-org-row-selected" : ""}`}
          >
            <Initials value={employee.initials} />
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
    );
  }

  return (
    <DataTable<Employee>
      tableId="admin.org.employees"
      caption={label}
      scrollLabel={label}
      rows={items}
      rowKey={(row) => row.id}
      rowAttrs={(row) => ({ className: row.id === selectedId ? "pf-org-table-row-selected" : "" })}
      columns={[
        {
          id: "employee",
          header: t("admin.org.columns.employee"),
          width: 286,
          cell: (employee) => (
            <div>
              <NameLink
                employee={employee}
                selected={employee.id === selectedId}
                href={hrefOf(employee.id)}
              />
              <div className="pf-hint pf-org-email">{employee.email}</div>
            </div>
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
