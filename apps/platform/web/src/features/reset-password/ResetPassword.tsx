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
import { employeeErrorText } from "../../entities/employee/errors";
import { lines } from "../first-run/lines";
import { TemporaryPasswordCard } from "../temporary-password/TemporaryPasswordCard";
import { useIssueTemporaryPasswordAction } from "../temporary-password/useTemporaryPassword";
import { resetErrorKey } from "./errors";

import "../assign-role/assign-role.css";

type Method = "email" | "temporary";

/**
 * «Сбросить пароль» в карточке сотрудника (W13-A6, BFF 0.12.0): вторичное действие с подтверждением на месте и блоком
 * «Что произойдёт». Способ «по почте» — CRM шлёт письмо с новым временным паролем и завершает сессии сотрудника.
 * «Временным паролем» — без почты: эндпоинт W13-A4 (`POST /admin/users/{id}/temporary-password`), пароль показывается
 * один раз тем же окном `TemporaryPasswordCard`. Себе сбросить нельзя (и в BFF — 409).
 */
export function ResetPassword({ employee, selfId }: { employee: Employee; selfId: string }) {
  const { t } = useTranslation("audit");
  const { t: tm } = useTranslation("modules");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const hintId = useId();
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<Method>("email");
  const own = employee.id === selfId;
  const [issued, setIssued] = useState<string | null>(null);
  const issue = useIssueTemporaryPasswordAction();
  const reset = useResetEmployeePasswordByEmail({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
        void message.success(t("resetPassword.sent", { email: employee.email }));
        setOpen(false);
      },
    },
  });

  if (issued !== null) {
    return (
      <TemporaryPasswordCard
        employee={employee}
        password={issued}
        onDone={() => {
          setIssued(null);
          setOpen(false);
          setMethod("email");
        }}
      />
    );
  }

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
        <Radio value="temporary" aria-describedby={`${hintId}-temp`}>
          {t("resetPassword.byTemporary")}
        </Radio>
      </Radio.Group>
      <p className="pf-hint" id={`${hintId}-temp`} style={{ margin: 0 }}>
        {t("resetPassword.temporaryHint")}
      </p>
      <Consequence
        title={t("resetPassword.whatHappens")}
        items={
          method === "email"
            ? [
                t("resetPassword.step1", { email: employee.email }),
                t("resetPassword.step2"),
                t("resetPassword.step3"),
              ]
            : lines(tm, "admin.org.password.issue.consequence")
        }
      />
      {method === "temporary" && issue.isError ? (
        <Alert type="error" showIcon role="alert" message={employeeErrorText(tm, issue.error)} />
      ) : null}
      {method === "email" && errorKey ? (
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
          loading={method === "email" ? reset.isPending : issue.isPending}
          onClick={() => {
            if (method === "email") {
              reset.mutate({ id: employee.id });
              return;
            }
            issue.mutate(
              { id: employee.id },
              {
                onSuccess: (credentials) => {
                  setIssued(credentials.temporary_password);
                  // Пароль остался только в состоянии окна: из кэша мутации он убирается сразу.
                  issue.reset();
                },
              },
            );
          }}
        >
          {t(method === "email" ? "resetPassword.confirm" : "resetPassword.confirmTemporary")}
        </Button>
        <Button
          onClick={() => {
            setOpen(false);
            setMethod("email");
            reset.reset();
            issue.reset();
          }}
        >
          {t("resetPassword.cancel")}
        </Button>
      </div>
    </div>
  );
}
