import { useQueryClient } from "@tanstack/react-query";
import { Checkbox } from "antd";
import { useTranslation } from "react-i18next";

import type { Employee } from "../../shared/api/generated/model";
import {
  getGetCapabilityMatrixQueryKey,
  getListEmployeesQueryKey,
  useUpdateEmployee,
} from "../../shared/api/generated/platform-bff";

/**
 * «Служебная учётная запись — не показывать в команде» (ДОСТ-1п): тестовый или технический вход. В списке сотрудников она
 * остаётся с меткой, чтобы ею можно было управлять, а в таблицах «кто что может» и подсчётах команды её нет.
 */
export function ServiceAccountToggle({ employee }: { employee: Employee }) {
  const { t } = useTranslation("modules");
  const queryClient = useQueryClient();
  const update = useUpdateEmployee({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getGetCapabilityMatrixQueryKey() }),
        ]),
    },
  });
  return (
    <Checkbox
      checked={employee.is_service === true}
      disabled={update.isPending}
      onChange={(event) => {
        update.mutate({ id: employee.id, data: { is_service: event.target.checked } });
      }}
    >
      {t("admin.org.service.label")}
    </Checkbox>
  );
}
