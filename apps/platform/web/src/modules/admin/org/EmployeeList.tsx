import { Table } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Employee } from "../../../shared/api/generated/model";
import { AccessTags, EmployeeStatusTag, Initials, RoleTags } from "./EmployeeCells";

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
    <Table<Employee>
      rowKey="id"
      dataSource={[...items]}
      pagination={false}
      tableLayout="fixed"
      rowClassName={(employee) => (employee.id === selectedId ? "pf-org-table-row-selected" : "")}
      aria-label={label}
      columns={[
        {
          title: t("admin.org.columns.employee"),
          key: "employee",
          width: "26%",
          render: (_, employee) => (
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
          title: t("admin.org.columns.position"),
          key: "position",
          width: "19%",
          render: (_, employee) =>
            employee.position ?? <span className="pf-hint">{t("admin.org.noPosition")}</span>,
        },
        {
          title: t("admin.org.columns.roles"),
          key: "roles",
          width: "19%",
          render: (_, employee) => <RoleTags roles={employee.roles} />,
        },
        {
          title: t("admin.org.columns.access"),
          key: "access",
          width: "20%",
          render: (_, employee) => <AccessTags employee={employee} />,
        },
        {
          title: t("admin.org.columns.status"),
          key: "status",
          width: "16%",
          render: (_, employee) => <EmployeeStatusTag status={employee.status} />,
        },
      ]}
    />
  );
}
