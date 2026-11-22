import { useQueryClient } from "@tanstack/react-query";
import { Button } from "antd";
import { useTranslation } from "react-i18next";

import type { Employee } from "../../shared/api/generated/model";
import {
  getListEmployeesQueryKey,
  useRetryEmployeeErpSync,
} from "../../shared/api/generated/platform-bff";

/** «Повторить» при сбое выдачи доступа в ERP (СЦ-8): CRM ставит задачу снова, статус — «выдаётся» до ответа ERP. */
export function RetryErpSync({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  const queryClient = useQueryClient();
  const retry = useRetryEmployeeErpSync({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() }),
    },
  });
  return (
    <Button
      loading={retry.isPending}
      onClick={() => {
        retry.mutate({ id: employee.id });
      }}
    >
      {t("admin.org.card.erpRetry")}
    </Button>
  );
}
