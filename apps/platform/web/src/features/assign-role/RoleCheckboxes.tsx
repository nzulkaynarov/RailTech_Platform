import { Alert, Button, Checkbox, Skeleton } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { rolesAccess } from "../../entities/role/roles";
import { moduleName } from "../../modules/registry";
import type { Role } from "../../shared/api/generated/model";
import "./assign-role.css";

/** Модули роли подписью под её названием — из её матрицы (данные роли, а не код). */
function moduleNames(t: (key: string) => string, role: Role): string {
  return rolesAccess([role])
    .modules.map((code) => moduleName(t, code))
    .join(", ");
}

export interface RoleCheckboxesProps {
  /** Роли компании (`GET /admin/roles`) */
  roles: readonly Role[];
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  /** Id выбранных ролей */
  value: readonly string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  /** Сообщение под группой (ошибка или подсказка); связано с группой через `aria-describedby` */
  note?: { id: string; text: string } | null;
}

/** Роли Платформы флажками: можно выдать несколько (ADR-0012). Группа — `fieldset` с `legend`. */
export function RoleCheckboxes({
  roles,
  loading,
  error,
  onRetry,
  value,
  onChange,
  disabled,
  note,
}: RoleCheckboxesProps) {
  const { t } = useTranslation(["modules", "shell"]);
  const hintId = useId();
  const describedBy = [hintId, note?.id].filter(Boolean).join(" ");
  const order = roles.map((role) => role.id);
  return (
    <fieldset className="pf-roles" aria-describedby={describedBy} disabled={disabled}>
      <legend className="pf-roles-legend">{t("modules:admin.org.form.rolesLegend")}</legend>
      <p id={hintId} className="pf-hint" style={{ margin: "0 0 8px" }}>
        {t("modules:admin.org.form.rolesHint")}
      </p>
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} title={false} />
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message={t("modules:admin.org.form.rolesError")}
          action={
            onRetry ? (
              <Button size="small" onClick={onRetry}>
                {t("modules:admin.org.loadError.retry")}
              </Button>
            ) : null
          }
        />
      ) : (
        <ul className="pf-roles-list">
          {roles.map((role) => (
            <li key={role.id}>
              <Checkbox
                checked={value.includes(role.id)}
                disabled={disabled}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...value, role.id]
                    : value.filter((id) => id !== role.id);
                  onChange(order.filter((id) => next.includes(id)));
                }}
              >
                <span className="pf-role-name">
                  {role.name}
                  {role.system ? (
                    <span className="pf-role-system"> · {t("modules:admin.roles.system")}</span>
                  ) : null}
                </span>
                <span className="pf-role-modules">
                  {moduleNames(t, role) || t("modules:admin.roles.noModules")}
                </span>
              </Checkbox>
            </li>
          ))}
        </ul>
      )}
      {note ? (
        <p id={note.id} className="pf-roles-note">
          {note.text}
        </p>
      ) : null}
    </fieldset>
  );
}
