import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import { AssignRoleForm } from "../../../features/assign-role/AssignRoleForm";
import { DisableEmployee } from "../../../features/assign-role/DisableEmployee";
import { ResetPassword } from "../../../features/reset-password/ResetPassword";
import { ResendInvite } from "../../../features/invite-employee/ResendInvite";
import { erpAttention } from "../../../entities/employee/status";
import type { Employee } from "../../../shared/api/generated/model";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import {
  CrmTag,
  EmployeeStatusTag,
  ErpTag,
  Initials,
  RoleTags,
  TelegramText,
} from "./EmployeeCells";

export interface EmployeeCardProps {
  employee: Employee;
  /** `Me.id` работающего администратора */
  selfId: string;
  /** Раздел `admin` на запись (ADMIN); у DIRECTOR — только просмотр */
  canEdit: boolean;
  /** Активные администраторы кроме этого сотрудника (для заранее показанного запрета «последнего админа») */
  otherActiveAdmins: number;
}

/** Карточка сотрудника в боковом окне: реквизиты, выдача ролей одной кнопкой, отключение (SPEC-v3 §7.6). */
export function EmployeeCard({ employee, selfId, canEdit, otherActiveAdmins }: EmployeeCardProps) {
  const { t } = useTranslation("modules");
  const attention = erpAttention(employee);
  const disabled = employee.status === "disabled";
  return (
    <div className="pf-panel-stack">
      <div className="pf-org-person">
        <Initials value={employee.initials} size={44} />
        <div style={{ minWidth: 0 }}>
          <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
            {employee.name}
          </h3>
          <EmployeeStatusTag status={employee.status} />
        </div>
      </div>
      <DefinitionList
        items={[
          { label: t("admin.org.card.email"), value: employee.email },
          { label: t("admin.org.card.position"), value: employee.position },
          ...(canEdit && !disabled
            ? []
            : [{ label: t("admin.org.card.roles"), value: <RoleTags roles={employee.roles} /> }]),
          { label: t("admin.org.card.crm"), value: <CrmTag employee={employee} /> },
          { label: t("admin.org.card.erp"), value: <ErpTag employee={employee} /> },
          {
            label: t("admin.org.card.telegram"),
            value: <TelegramText linked={employee.telegram_linked} />,
          },
        ]}
      />
      {attention === "pending" ? (
        <Alert type="info" showIcon message={t("admin.org.card.erpPending")} />
      ) : null}
      {attention === "error" ? (
        <Alert
          type="error"
          showIcon
          message={t("admin.org.card.erpError", { error: employee.erp_sync_error ?? "—" })}
        />
      ) : null}
      {!canEdit ? (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("admin.org.readOnly")}
        </p>
      ) : disabled ? (
        <>
          <Alert type="info" showIcon message={t("admin.org.card.disabledNote")} />
          <DisableEmployee
            employee={employee}
            selfId={selfId}
            otherActiveAdmins={otherActiveAdmins}
          />
        </>
      ) : (
        <>
          <AssignRoleForm
            employee={employee}
            selfId={selfId}
            otherActiveAdmins={otherActiveAdmins}
          />
          {employee.status === "invited" ? <ResendInvite employee={employee} /> : null}
          <ResetPassword employee={employee} selfId={selfId} />
          <DisableEmployee
            employee={employee}
            selfId={selfId}
            otherActiveAdmins={otherActiveAdmins}
          />
        </>
      )}
    </div>
  );
}
