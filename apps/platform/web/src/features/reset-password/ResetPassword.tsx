import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Radio } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Employee } from "../../shared/api/generated/model";
import {
  getListEmployeesQueryKey,
  useResetEmployeePasswordByEmail,
} from "../../shared/api/generated/platform-bff";
import { Consequence } from "../../shared/ui/Consequence";
import { resetErrorKey } from "./errors";

import "../assign-role/assign-role.css";

type Method = "email" | "temporary";

/**
 * «Сбросить пароль» в карточке сотрудника (W13-A6, BFF 0.12.0): вторичное действие с подтверждением на месте и блоком
 * «Что произойдёт». Способ «по почте» — CRM шлёт письмо с новым временным паролем и завершает сессии сотрудника.
 * «Временным паролем» (без почты) подключается к выдаче пароля администратору отдельно. Себе сбросить нельзя.
 */
export function ResetPassword({ employee, selfId }: { employee: Employee; selfId: string }) {
  const { t } = useTranslation("audit");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const hintId = useId();
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<Method>("email");
  const own = employee.id === selfId;
  const reset = useResetEmployeePasswordByEmail({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
        void message.success(t("resetPassword.sent", { email: employee.email }));
        setOpen(false);
      },
    },
  });

  if (!open) {
    return (
      <div className="pf-panel-stack" style={{ gap: 8 }}>
        <Button
          block
          disabled={own}
          aria-describedby={own ? hintId : undefined}
          onClick={() => {
            setOpen(true);
          }}
        >
          {t("resetPassword.button")}
        </Button>
        {own ? (
          <p className="pf-hint" id={hintId} style={{ margin: 0 }}>
            {t("resetPassword.self")}
          </p>
        ) : null}
      </div>
    );
  }

  const errorKey = reset.isError ? resetErrorKey(reset.error) : null;
  return (
    <div className="pf-panel-stack" role="group" aria-label={t("resetPassword.title")}>
      <Radio.Group
        aria-label={t("resetPassword.method")}
        value={method}
        onChange={(event) => {
          setMethod(event.target.value as Method);
        }}
        style={{ display: "flex", flexDirection: "column", gap: 4 }}
      >
        <Radio value="email">{t("resetPassword.byEmail")}</Radio>
        <Radio value="temporary" disabled aria-describedby={`${hintId}-temp`}>
          {t("resetPassword.byTemporary")}
        </Radio>
      </Radio.Group>
      <p className="pf-hint" id={`${hintId}-temp`} style={{ margin: 0 }}>
        {t("resetPassword.temporaryUnavailable")}
      </p>
      <Consequence
        title={t("resetPassword.whatHappens")}
        items={[
          t("resetPassword.step1", { email: employee.email }),
          t("resetPassword.step2"),
          t("resetPassword.step3"),
        ]}
      />
      {errorKey ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={t(`resetPassword.errors.${errorKey}`)}
          description={
            errorKey === "NOT_CONFIGURED" ? (
              <Link to="/admin/integrations">{t("resetPassword.integrations")}</Link>
            ) : undefined
          }
        />
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          type="primary"
          loading={reset.isPending}
          onClick={() => {
            reset.mutate({ id: employee.id });
          }}
        >
          {t("resetPassword.confirm")}
        </Button>
        <Button
          onClick={() => {
            setOpen(false);
            reset.reset();
          }}
        >
          {t("resetPassword.cancel")}
        </Button>
      </div>
    </div>
  );
}
