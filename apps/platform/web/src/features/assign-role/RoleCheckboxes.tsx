import { Checkbox } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { ROLES, type RoleCode } from "../../app/rbac.generated";
import { modulesOfRoles } from "../../entities/employee/access";
import { findModule } from "../../modules/registry";

import "./assign-role.css";

/** Модули роли подписью под её названием — из сгенерированной матрицы. */
function moduleNames(role: RoleCode): string {
  return modulesOfRoles([role])
    .map((code) => findModule(code)?.name ?? code)
    .join(", ");
}

export interface RoleCheckboxesProps {
  value: readonly RoleCode[];
  onChange: (roles: RoleCode[]) => void;
  disabled?: boolean;
  /** Сообщение под группой (ошибка или подсказка); связано с группой через `aria-describedby` */
  note?: { id: string; text: string } | null;
}

/** Шесть ролей Платформы флажками: можно выдать несколько (SPEC-v3 §4.1). Группа — `fieldset` с `legend`. */
export function RoleCheckboxes({ value, onChange, disabled, note }: RoleCheckboxesProps) {
  const { t } = useTranslation(["modules", "shell"]);
  const hintId = useId();
  const describedBy = [hintId, note?.id].filter(Boolean).join(" ");
  return (
    <fieldset className="pf-roles" aria-describedby={describedBy} disabled={disabled}>
      <legend className="pf-roles-legend">{t("modules:admin.org.form.rolesLegend")}</legend>
      <p id={hintId} className="pf-hint" style={{ margin: "0 0 8px" }}>
        {t("modules:admin.org.form.rolesHint")}
      </p>
      <ul className="pf-roles-list">
        {ROLES.map((role) => (
          <li key={role}>
            <Checkbox
              checked={value.includes(role)}
              disabled={disabled}
              onChange={(event) => {
                const next = event.target.checked
                  ? [...value, role]
                  : value.filter((r) => r !== role);
                onChange(ROLES.filter((r) => next.includes(r)));
              }}
            >
              {/* TODO(ADR-0012): список ролей и их названия — из `GET /admin/roles` (роли администратор создаёт сам), не `ROLES` и i18n по коду. */}
              <span className="pf-role-name">{t(`shell:roles.${role}`)}</span>
              <span className="pf-role-modules">{moduleNames(role)}</span>
            </Checkbox>
          </li>
        ))}
      </ul>
      {note ? (
        <p id={note.id} className="pf-roles-note">
          {note.text}
        </p>
      ) : null}
    </fieldset>
  );
}
