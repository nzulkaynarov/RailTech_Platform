import { Alert, App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { employeeErrorText } from "../../entities/employee/errors";
import { isSystemAdmin } from "../../entities/role/roles";
import type { Employee } from "../../shared/api/generated/model";
import { Consequence } from "../../shared/ui/Consequence";
import { hasActiveLeads } from "./leads";
import { TransferLeads } from "./TransferLeads";
import { useEmployeeUpdate } from "./useEmployeeMutations";

import "./assign-role.css";

export interface DisableEmployeeProps {
  employee: Employee;
  selfId: string;
  /** Отключение последнего администратора CRM запретит (409 `LAST_ADMIN`); форма предупреждает заранее */
  otherActiveAdmins: number;
}

/**
 * Отключение и включение сотрудника: вторичное действие карточки с подтверждением на месте (без модального окна) и
 * блоком «Что произойдёт». Сессии гасит CRM (docs/architecture/platform-bff.md §3); решение о праве — за CRM.
 */
export function DisableEmployee({ employee, selfId, otherActiveAdmins }: DisableEmployeeProps) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const [confirming, setConfirming] = useState(false);
  const [transferTo, setTransferTo] = useState<string | null>(null);
  const disabled = employee.status === "disabled";
  const update = useEmployeeUpdate(selfId, () => {
    setConfirming(false);
    setTransferTo(null);
    void message.success(t("admin.org.form.saved"));
  });
  const lastAdmin = !disabled && employee.roles.some(isSystemAdmin) && otherActiveAdmins === 0;
  const leads = update.isError && hasActiveLeads(update.error);

  const run = () => {
    update.mutate({
      id: employee.id,
      data: {
        is_active: disabled,
        ...(leads && transferTo ? { transfer_to_user_id: transferTo } : {}),
      },
    });
  };

  if (!confirming) {
    return (
      <div className="pf-panel-stack">
        {lastAdmin ? (
          <p className="pf-roles-note" id={`disable-block-${employee.id}`}>
            {t("admin.org.errors.LAST_ADMIN")}
          </p>
        ) : null}
        <Button
          danger={!disabled}
          block
          disabled={lastAdmin}
          aria-describedby={lastAdmin ? `disable-block-${employee.id}` : undefined}
          onClick={() => {
            setConfirming(true);
          }}
        >
          {disabled ? t("admin.org.disable.enable") : t("admin.org.disable.button")}
        </Button>
      </div>
    );
  }

  return (
    <div
      className="pf-panel-stack"
      role="group"
      aria-label={disabled ? t("admin.org.disable.enableTitle") : t("admin.org.disable.title")}
    >
      <Consequence
        items={
          disabled
            ? [t("admin.org.disable.enableResult")]
            : [
                t("admin.org.disable.sessions"),
                t("admin.org.disable.terms"),
                t("admin.org.disable.kept"),
              ]
        }
      />
      {update.isError ? (
        <Alert type="error" showIcon message={employeeErrorText(t, update.error)} role="alert" />
      ) : null}
      {leads ? (
        <TransferLeads employee={employee} value={transferTo} onChange={setTransferTo} />
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          danger={!disabled}
          loading={update.isPending}
          disabled={leads && !transferTo}
          onClick={run}
        >
          {disabled ? t("admin.org.disable.enableConfirm") : t("admin.org.disable.confirm")}
        </Button>
        <Button
          onClick={() => {
            setConfirming(false);
            update.reset();
          }}
        >
          {t("admin.org.disable.cancel")}
        </Button>
      </div>
    </div>
  );
}
