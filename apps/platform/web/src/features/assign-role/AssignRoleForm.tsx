import { Alert, App, Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { accessOfRoleIds } from "../../entities/employee/access";
import { backendConsequence } from "../../entities/employee/consequence";
import { employeeErrorText } from "../../entities/employee/errors";
import { isSystemAdmin } from "../../entities/role/roles";
import type { Employee } from "../../shared/api/generated/model";
import { Consequence } from "../../shared/ui/Consequence";
import { findModule } from "../../modules/registry";
import { RoleCheckboxes } from "./RoleCheckboxes";
import { useRoles } from "./useRoles";
import { hasActiveLeads } from "./leads";
import { TransferLeads } from "./TransferLeads";
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
 * Выдача ролей в карточке сотрудника (SPEC-v3 §7.6, ADR-0012): роли — из списка ролей компании (`GET /admin/roles`),
 * несколько ролей и должность одной кнопкой «Сохранить роли», под ней — «Что произойдёт» из матриц выбранных ролей.
 * Сохранение — `PATCH /admin/users/{id}` с полным набором id; запреты («последний администратор», лиды в работе)
 * принадлежат CRM, форма заранее показывает запрет снять последнего администратора и предлагает передать лиды.
 */
export function AssignRoleForm({ employee, selfId, otherActiveAdmins }: AssignRoleFormProps) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const noteId = useId();
  const positionId = useId();
  const { query, roles } = useRoles();
  const [draftRoles, setDraftRoles] = useState<string[] | null>(null);
  const [draftPosition, setDraftPosition] = useState<string | null>(null);
  const [transferTo, setTransferTo] = useState<string | null>(null);
  const update = useEmployeeUpdate(selfId, () => {
    setDraftRoles(null);
    setDraftPosition(null);
    setTransferTo(null);
    void message.success(t("admin.org.form.saved"));
  });

  const current = employee.roles.map((role) => role.id);
  const selected = draftRoles ?? current;
  const position = draftPosition ?? employee.position ?? "";
  const rolesChanged =
    selected.length !== current.length || selected.some((id) => !current.includes(id));
  const positionChanged = position.trim() !== (employee.position ?? "");
  const dirty = rolesChanged || positionChanged;
  const isSelf = employee.id === selfId;
  const adminRole = roles.find(isSystemAdmin);
  const dropsLastAdmin =
    employee.roles.some(isSystemAdmin) &&
    adminRole !== undefined &&
    !selected.includes(adminRole.id) &&
    otherActiveAdmins === 0;
  const noRoles = selected.length === 0;
  const blocker = dropsLastAdmin
    ? t("admin.org.form.lastAdmin")
    : noRoles
      ? t("admin.org.form.needRole")
      : null;

  const before = accessOfRoleIds(roles, current);
  const after = accessOfRoleIds(roles, selected);
  const lost = before.modules.filter((m) => !after.modules.includes(m));
  const items = [
    t("admin.org.consequence.modules", { modules: moduleList(after.modules) || "—" }),
    ...(lost.length > 0 ? [t("admin.org.consequence.lost", { modules: moduleList(lost) })] : []),
    ...backendConsequence(t, after),
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
  const leads = update.isError && hasActiveLeads(update.error);

  const save = () => {
    update.mutate({
      id: employee.id,
      data: {
        ...(rolesChanged ? { role_ids: selected } : {}),
        ...(positionChanged ? { position: position.trim() } : {}),
        ...(leads && transferTo ? { transfer_to_user_id: transferTo } : {}),
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
        roles={roles}
        loading={query.isPending}
        error={query.isError}
        onRetry={() => {
          void query.refetch();
        }}
        value={selected}
        onChange={setDraftRoles}
        note={blocker ? { id: noteId, text: blocker } : null}
      />
      {update.isError ? (
        <Alert type="error" showIcon message={employeeErrorText(t, update.error)} role="alert" />
      ) : null}
      {leads ? (
        <TransferLeads employee={employee} value={transferTo} onChange={setTransferTo} />
      ) : null}
      <div>
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={update.isPending}
          disabled={!dirty || blocker !== null || (leads && !transferTo)}
        >
          {leads ? t("admin.org.transfer.save") : t("admin.org.form.save")}
        </Button>
      </div>
      {blocker ? null : <Consequence items={items} />}
    </form>
  );
}
