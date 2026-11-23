import { Alert, App, Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../shared/api/errors";
import type { Employee } from "../../shared/api/generated/model";
import { useResetEmployeeSecondFactor } from "../../shared/api/generated/platform-bff";

import "../assign-role/assign-role.css";

/**
 * «Сбросить второй фактор» в карточке сотрудника (ДВ-4б): потерян телефон. Подтверждение на месте с причиной — она
 * попадает в журнал CRM; сессии сотрудника закрываются, при следующем входе он настраивает код заново. Себе нельзя:
 * свой фактор сбрасывает другой администратор.
 */
export function ResetSecondFactor({ employee, selfId }: { employee: Employee; selfId: string }) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const own = employee.id === selfId;
  const reset = useResetEmployeeSecondFactor({
    mutation: {
      onSuccess: () => {
        void message.success(t("admin.org.resetFactor.done", { name: employee.name }));
        setOpen(false);
        setReason("");
      },
    },
  });

  if (!open) {
    return (
      <div className="pf-panel-stack" style={{ gap: 8 }}>
        <Button
          block
          disabled={own}
          aria-describedby={own ? `${id}-own` : undefined}
          onClick={() => {
            setOpen(true);
          }}
        >
          {t("admin.org.resetFactor.button")}
        </Button>
        {own ? (
          <p className="pf-hint" id={`${id}-own`} style={{ margin: 0 }}>
            {t("admin.org.resetFactor.self")}
          </p>
        ) : null}
      </div>
    );
  }

  const reasonKey =
    reset.error instanceof ApiError && reset.error.details["reason"] === "second_factor_not_enabled"
      ? "notEnabled"
      : "default";
  const valid = reason.trim().length >= 3;
  return (
    <div className="pf-panel-stack" role="group" aria-label={t("admin.org.resetFactor.title")}>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("admin.org.resetFactor.what")}
      </p>
      <div>
        <label htmlFor={id} style={{ display: "block", marginBottom: 4 }}>
          {t("admin.org.resetFactor.reason")}
        </label>
        <Input
          id={id}
          value={reason}
          maxLength={500}
          autoComplete="off"
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </div>
      {reset.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={t(`admin.org.resetFactor.errors.${reasonKey}`)}
        />
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          danger
          type="primary"
          loading={reset.isPending}
          disabled={!valid}
          onClick={() => {
            reset.mutate({ id: employee.id, data: { reason: reason.trim() } });
          }}
        >
          {t("admin.org.resetFactor.confirm")}
        </Button>
        <Button
          onClick={() => {
            setOpen(false);
            reset.reset();
          }}
        >
          {t("admin.org.resetFactor.cancel")}
        </Button>
      </div>
    </div>
  );
}
