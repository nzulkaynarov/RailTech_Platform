import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import { CapabilityCard } from "../../../features/capabilities/CapabilityCard";
import { AssignRoleForm } from "../../../features/assign-role/AssignRoleForm";
import { EmployeeDeputy } from "../../../features/assign-deputy/EmployeeDeputy";
import { ServiceAccountToggle } from "../../../features/assign-role/ServiceAccountToggle";
import { DisableEmployee } from "../../../features/assign-role/DisableEmployee";
import { RetryErpSync } from "../../../features/assign-role/RetryErpSync";
import { ResetPassword } from "../../../features/reset-password/ResetPassword";
import { ResetSecondFactor } from "../../../features/reset-second-factor/ResetSecondFactor";
import { ResendInvite } from "../../../features/invite-employee/ResendInvite";
import { erpAttention, erpSyncReason } from "../../../entities/employee/status";
import type { Employee } from "../../../shared/api/generated/model";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmployeeStatusTag, RoleTags, TelegramText } from "./EmployeeCells";
import { useFormat } from "../../../shared/lib/useFormat";
import { PersonAvatar } from "../../../shared/ui/EntityCell";
import { StatusTag } from "../../../shared/ui/StatusTag";

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
  const format = useFormat();
  const attention = erpAttention(employee);
  const erpReason = erpSyncReason(employee.erp_sync_error);
  const disabled = employee.status === "disabled";
  return (
    <div className="pf-panel-stack">
      <div className="pf-org-person">
        <PersonAvatar name={employee.name} size={40} />
        <div style={{ minWidth: 0 }}>
          <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
            {employee.name}
          </h3>
          <EmployeeStatusTag status={employee.status} />
          {employee.is_service ? (
            <>
              {" "}
              <StatusTag tone="default">{t("admin.org.service.tag")}</StatusTag>
            </>
          ) : null}
        </div>
      </div>
      <DefinitionList
        items={[
          { label: t("admin.org.card.email"), value: employee.email },
          { label: t("admin.org.card.position"), value: employee.position },
          ...(canEdit && !disabled
            ? []
            : [{ label: t("admin.org.card.roles"), value: <RoleTags roles={employee.roles} /> }]),
          {
            label: t("admin.org.card.telegram"),
            value: <TelegramText state={employee.telegram} />,
          },
          // Форма «Замещение» ниже есть только у администратора и у действующего сотрудника: остальным — строка
          ...(employee.deputy && !(canEdit && !disabled)
            ? [
                {
                  label: t("admin.org.deputy.title"),
                  value: t("admin.org.deputy.line", {
                    name: employee.deputy.name,
                    from: format.date(employee.deputy.date_from, "date"),
                    to: format.date(employee.deputy.date_to, "date"),
                  }),
                },
              ]
            : []),
        ]}
      />
      <CapabilityCard
        employeeId={employee.id}
        {...(canEdit && !disabled ? { rolesTargetId: `pf-roles-${employee.id}` } : {})}
      />
      {attention === "pending" ? (
        <Alert type="info" showIcon message={t("admin.org.card.erpPending")} />
      ) : null}
      {attention === "error" ? (
        <Alert
          type="error"
          showIcon
          message={
            erpReason
              ? t(`admin.org.card.erpReason.${erpReason}`)
              : t("admin.org.card.erpNotGranted")
          }
          action={canEdit ? <RetryErpSync employee={employee} /> : undefined}
        />
      ) : null}
      {!canEdit ? null : disabled ? (
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
          <div id={`pf-roles-${employee.id}`} tabIndex={-1}>
            <AssignRoleForm
              employee={employee}
              selfId={selfId}
              otherActiveAdmins={otherActiveAdmins}
            />
          </div>
          <ServiceAccountToggle employee={employee} />
          <EmployeeDeputy employee={employee} selfId={selfId} />
          {employee.status === "invited" ? <ResendInvite employee={employee} /> : null}
          <ResetPassword employee={employee} selfId={selfId} />
          <ResetSecondFactor employee={employee} selfId={selfId} />
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
