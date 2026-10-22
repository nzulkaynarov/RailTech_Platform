import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button } from "antd";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../shared/api/errors";
import type { Employee } from "../../shared/api/generated/model";
import { getListEmployeesQueryKey, useResendInvite } from "../../shared/api/generated/platform-bff";

/**
 * «Отправить приглашение снова» у сотрудника со статусом «Приглашён» (Q-PLT-15-1 п. 3, BFF 0.3.0). CRM меняет временный
 * пароль только при отправке письма: без подключённой почты пароль прежний, письмо не уходит — говорим об этом словами.
 */
export function ResendInvite({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const resend = useResendInvite({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
        void message.success(t("admin.org.invite.sent", { email: employee.email }));
      },
    },
  });
  const notSent = resend.error instanceof ApiError && resend.error.details["invite"] === "not_sent";
  return (
    <div className="pf-panel-stack" style={{ gap: 8 }}>
      <Button
        block
        loading={resend.isPending}
        onClick={() => {
          resend.mutate({ id: employee.id });
        }}
      >
        {t("admin.org.invite.resend")}
      </Button>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("admin.org.invite.resendHint")}
      </p>
      {resend.isError ? (
        <Alert
          type={notSent ? "warning" : "error"}
          showIcon
          role="alert"
          message={t(notSent ? "admin.org.invite.resendNotSent" : "admin.org.errors.DEFAULT")}
        />
      ) : null}
    </div>
  );
}
