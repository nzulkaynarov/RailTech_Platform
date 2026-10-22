import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { Employee } from "../../shared/api/generated/model";
import { useListEmployees } from "../../shared/api/generated/platform-bff";

/**
 * Кому передать лиды (ADR-0015, Q-PLT-15-1 п. 4): выбор активного коллеги; повтор сохранения уходит в CRM с
 * `transfer_to_user_id`. Коллеги — из списка Оргструктуры (он уже загружен на странице). Нативный `select` — договорённость
 * по доступности для выбора из списка в формах.
 */
export function TransferLeads({
  employee,
  value,
  onChange,
}: {
  employee: Employee;
  value: string | null;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation("modules");
  const id = useId();
  const list = useListEmployees();
  const colleagues = (list.data?.items ?? []).filter(
    (e) => e.id !== employee.id && e.status === "active",
  );
  return (
    <div>
      <label htmlFor={id} style={{ display: "block", marginBottom: 4 }}>
        {t("admin.org.transfer.label")}
      </label>
      <select
        id={id}
        className="pf-native-select pf-focusable"
        value={value ?? ""}
        onChange={(event) => {
          if (event.target.value) onChange(event.target.value);
        }}
      >
        <option value="" disabled>
          {t("admin.org.transfer.placeholder")}
        </option>
        {colleagues.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name}
          </option>
        ))}
      </select>
    </div>
  );
}
