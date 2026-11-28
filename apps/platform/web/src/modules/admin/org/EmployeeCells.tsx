import { useTranslation } from "react-i18next";

import { erpAttention } from "../../../entities/employee/status";
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

/**
 * Доступ к учёту: метка только когда есть что сказать — «Доступ выдаётся» (жёлтая) и «Доступ не выдан» (красная).
 * Выданный и невыданный по праву доступ молчат: «Контакты» открыты всем сотрудникам, лишняя метка — шум.
 */
export function ErpTag({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  const attention = erpAttention(employee);
  if (attention === "error") {
    return (
      <StatusTag kind="access" status="error">
        {t("admin.org.access.erpError")}
      </StatusTag>
    );
  }
  if (attention === "pending") {
    return (
      <StatusTag kind="access" status="pending">
        {t("admin.org.access.erpPending")}
      </StatusTag>
    );
  }
  return null;
}

/**
 * Telegram для уведомлений сотруднику, три состояния (СОТР-1): привязан — зелёный тег; не привязан — серый «Telegram: нет»;
 * привязан, но сообщения не доходят («Старт» не нажат или бот заблокирован) — жёлтый «Telegram: не доходит».
 */
export function TelegramTag({ state }: { state: Employee["telegram"] }) {
  const { t } = useTranslation("modules");
  if (state === "blocked") {
    return (
      <StatusTag kind="access" status="pending">
        {t("admin.org.access.telegramBlocked")}
      </StatusTag>
    );
  }
  return (
    <StatusTag kind="access" status={state === "linked" ? "yes" : "no"}>
      {t(state === "linked" ? "admin.org.access.telegram" : "admin.org.access.telegramNo")}
    </StatusTag>
  );
}

/** Доступ к учёту (только если выдаётся или не выдан) и Telegram для уведомлений словами в строке списка. */
export function AccessTags({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  return (
    <span className="pf-org-tags">
      {employee.is_service ? <StatusTag tone="default">{t("admin.org.service.tag")}</StatusTag> : null}
      <ErpTag employee={employee} />
      <TelegramTag state={employee.telegram} />
    </span>
  );
}

export function TelegramText({ state }: { state: Employee["telegram"] }) {
  const { t } = useTranslation("modules");
  const key = { linked: "linked", not_linked: "notLinked", blocked: "blocked" }[state];
  return <>{t(`admin.org.telegram.${key}`)}</>;
}

export function EmployeeStatusTag({ status }: { status: Employee["status"] }) {
  const { t } = useTranslation("modules");
  return (
    <StatusTag kind="employee" status={status}>
      {t(`admin.org.status.${status}`)}
    </StatusTag>
  );
}
