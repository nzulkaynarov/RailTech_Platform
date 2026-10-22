import { Alert, App, Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { RoleCode } from "../../app/rbac.generated";
import { modulesOfRoles } from "../../entities/employee/access";
import { erpConsequence } from "../../entities/employee/consequence";
import { employeeErrorText } from "../../entities/employee/errors";
import type { Employee } from "../../shared/api/generated/model";
import { Consequence } from "../../shared/ui/Consequence";
import { findModule } from "../../modules/registry";
import { RoleCheckboxes } from "./RoleCheckboxes";
import { useEmployeeUpdate } from "./useEmployeeMutations";

import "./assign-role.css";

export interface AssignRoleFormProps {
  employee: Employee;
  /** `Me.id` администратора, который работает с карточкой */
  selfId: string;
  /** Активные администраторы кроме этого сотрудника: решает CRM, форма только предупреждает заранее */
  otherActiveAdmins: number;
}

function moduleList(codes: readonly string[]): string {
  return codes.map((code) => findModule(code)?.name ?? code).join(", ");
}

/**
 * Выдача ролей в карточке сотрудника (SPEC-v3 §7.6): несколько ролей и должность одной кнопкой «Сохранить роли»,
 * под ней — «Что произойдёт» из сгенерированной матрицы. Сохранение — `PATCH /admin/users/{id}`; запрет снять роль
 * последнего администратора принадлежит CRM (409 `LAST_ADMIN`), форма заранее показывает тот же запрет текстом.
 */
export function AssignRoleForm({ employee, selfId, otherActiveAdmins }: AssignRoleFormProps) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const noteId = useId();
  const positionId = useId();
  const [draftRoles, setDraftRoles] = useState<RoleCode[] | null>(null);
  const [draftPosition, setDraftPosition] = useState<string | null>(null);
  const update = useEmployeeUpdate(selfId, () => {
    setDraftRoles(null);
    setDraftPosition(null);
    void message.success(t("admin.org.form.saved"));
  });

  const roles = draftRoles ?? employee.roles;
  const position = draftPosition ?? employee.position ?? "";
  const rolesChanged =
    roles.length !== employee.roles.length || roles.some((r) => !employee.roles.includes(r));
  const positionChanged = position.trim() !== (employee.position ?? "");
  const dirty = rolesChanged || positionChanged;

  const isSelf = employee.id === selfId;
  const dropsLastAdmin =
    employee.roles.includes("ADMIN") && !roles.includes("ADMIN") && otherActiveAdmins === 0;
  const noRoles = roles.length === 0;
  const blocker = dropsLastAdmin
    ? t("admin.org.form.lastAdmin")
    : noRoles
      ? t("admin.org.form.needRole")
      : null;

  const before = modulesOfRoles(employee.roles);
  const after = modulesOfRoles(roles);
  const lost = before.filter((m) => !after.includes(m));
  const erpLine = erpConsequence(t, roles);
  const items = [
    t("admin.org.consequence.modules", { modules: moduleList(after) || "—" }),
    ...(lost.length > 0 ? [t("admin.org.consequence.lost", { modules: moduleList(lost) })] : []),
    ...(erpLine ? [erpLine] : []),
    ...(positionChanged
      ? [
          position.trim()
            ? t("admin.org.consequence.position", { position: position.trim() })
            : t("admin.org.consequence.positionCleared"),
        ]
      : []),
    ...(isSelf
      ? [
          t("admin.org.consequence.self"),
          ...(lost.includes("admin") ? [t("admin.org.consequence.selfLosesAdmin")] : []),
        ]
      : []),
    t("admin.org.consequence.applied"),
  ];

  const save = () => {
    update.mutate({
      id: employee.id,
      data: {
        ...(rolesChanged ? { roles } : {}),
        ...(positionChanged ? { position: position.trim() } : {}),
      },
    });
  };

  return (
    <form
      className="pf-panel-stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (dirty && !blocker && !update.isPending) save();
      }}
      noValidate
    >
      <div>
        <label htmlFor={positionId} style={{ display: "block", marginBottom: 4 }}>
          {t("admin.org.form.positionLabel")}
        </label>
        <Input
          id={positionId}
          value={position}
          maxLength={120}
          autoComplete="off"
          aria-describedby={`${positionId}-hint`}
          onChange={(event) => {
            setDraftPosition(event.target.value);
          }}
        />
        <p id={`${positionId}-hint`} className="pf-hint" style={{ margin: "4px 0 0" }}>
          {t("admin.org.form.positionHint")}
        </p>
      </div>
      <RoleCheckboxes
        value={roles}
        onChange={setDraftRoles}
        note={blocker ? { id: noteId, text: blocker } : null}
      />
      {update.isError ? (
        <Alert type="error" showIcon message={employeeErrorText(t, update.error)} role="alert" />
      ) : null}
      <div>
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={update.isPending}
          disabled={!dirty || blocker !== null}
        >
          {t("admin.org.form.save")}
        </Button>
      </div>
      {blocker ? null : <Consequence items={items} />}
    </form>
  );
}
