import { useTranslation } from "react-i18next";

import { EMPLOYEE_STATUS_TONE, erpAttention } from "../../../entities/employee/status";
import type { Employee } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";

/** Роли сотрудника тегами со словом (названия — данные CRM); без ролей — подпись «Нет ролей». */
export function RoleTags({ roles }: { roles: Employee["roles"] }) {
  const { t } = useTranslation(["modules", "shell"]);
  if (roles.length === 0) return <span className="pf-hint">{t("modules:admin.org.noRoles")}</span>;
  return (
    <span className="pf-org-tags">
      {roles.map((role) => (
        <StatusTag key={role.id} tone="default">
          {role.name}
        </StatusTag>
      ))}
    </span>
  );
}

export function CrmTag({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  return (
    <StatusTag tone={employee.access.crm ? "green" : "default"}>
      {t(employee.access.crm ? "admin.org.access.crm" : "admin.org.access.crmNo")}
    </StatusTag>
  );
}

/** ERP: есть — зелёный, нет — серый «ERP: нет»; провижининг идёт — жёлтый, сбой — красный (всегда словом). */
export function ErpTag({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  const attention = erpAttention(employee);
  const [tone, key] =
    attention === "error"
      ? (["red", "erpError"] as const)
      : attention === "pending"
        ? (["gold", "erpPending"] as const)
        : employee.access.erp
          ? (["green", "erp"] as const)
          : (["default", "erpNo"] as const);
  return <StatusTag tone={tone}>{t(`admin.org.access.${key}`)}</StatusTag>;
}

/** Telegram для уведомлений сотруднику: привязан — зелёный тег, нет — серый «Telegram: нет». */
export function TelegramTag({ linked }: { linked: boolean }) {
  const { t } = useTranslation("modules");
  return (
    <StatusTag tone={linked ? "green" : "default"}>
      {t(linked ? "admin.org.access.telegram" : "admin.org.access.telegramNo")}
    </StatusTag>
  );
}

/** Доступ к CRM и ERP и Telegram для уведомлений словами в строке списка. */
export function AccessTags({ employee }: { employee: Employee }) {
  return (
    <span className="pf-org-tags">
      <CrmTag employee={employee} />
      <ErpTag employee={employee} />
      <TelegramTag linked={employee.telegram_linked} />
    </span>
  );
}

export function TelegramText({ linked }: { linked: boolean }) {
  const { t } = useTranslation("modules");
  return <>{t(linked ? "admin.org.telegram.linked" : "admin.org.telegram.notLinked")}</>;
}

export function EmployeeStatusTag({ status }: { status: Employee["status"] }) {
  const { t } = useTranslation("modules");
  return (
    <StatusTag tone={EMPLOYEE_STATUS_TONE[status]}>{t(`admin.org.status.${status}`)}</StatusTag>
  );
}

/** Инициалы в круге 36 px (как аватар рейла): декоративные, имя рядом словами. */
export function Initials({ value, size = 36 }: { value: string; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="pf-org-avatar"
      style={{ width: size, height: size, fontSize: size > 36 ? 14 : 12 }}
    >
      {value}
    </span>
  );
}
