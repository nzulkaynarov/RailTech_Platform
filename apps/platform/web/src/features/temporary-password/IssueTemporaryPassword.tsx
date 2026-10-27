import { Alert, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { employeeErrorText } from "../../entities/employee/errors";
import type { Employee } from "../../shared/api/generated/model";
import { Consequence } from "../../shared/ui/Consequence";
import { lines } from "../first-run/lines";
import { TemporaryPasswordCard } from "./TemporaryPasswordCard";
import { useIssueTemporaryPasswordAction } from "./useTemporaryPassword";

import "../assign-role/assign-role.css";

/**
 * «Выдать временный пароль» в карточке приглашённого сотрудника (без почты): подтверждение на месте с блоком «Что
 * произойдёт», затем пароль показывается один раз. Пока окно с паролем открыто, остальное в карточке не меняется.
 */
export function IssueTemporaryPassword({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  const [confirming, setConfirming] = useState(false);
  const [issued, setIssued] = useState<string | null>(null);
  const issue = useIssueTemporaryPasswordAction();

  if (issued !== null) {
    return (
      <TemporaryPasswordCard
        employee={employee}
        password={issued}
        onDone={() => {
          setIssued(null);
          setConfirming(false);
        }}
      />
    );
  }

  if (!confirming) {
    return (
      <div className="pf-panel-stack" style={{ gap: 8 }}>
        <Button
          block
          onClick={() => {
            setConfirming(true);
          }}
        >
          {t("admin.org.password.issue.button")}
        </Button>
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("admin.org.password.issue.hint")}
        </p>
      </div>
    );
  }

  return (
    <div
      className="pf-panel-stack"
      role="group"
      aria-label={t("admin.org.password.issue.confirmTitle")}
    >
      <Consequence items={lines(t, "admin.org.password.issue.consequence")} />
      {issue.isError ? (
        <Alert type="error" showIcon role="alert" message={employeeErrorText(t, issue.error)} />
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          type="primary"
          loading={issue.isPending}
          onClick={() => {
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
          {t("admin.org.password.issue.confirm")}
        </Button>
        <Button
          onClick={() => {
            setConfirming(false);
            issue.reset();
          }}
        >
          {t("admin.org.password.issue.cancel")}
        </Button>
      </div>
    </div>
  );
}
