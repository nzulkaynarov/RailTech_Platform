import { Select } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { Employee } from "../../shared/api/generated/model";
import { useListEmployees } from "../../shared/api/generated/platform-bff";

/**
 * Кому передать лиды (ADR-0015, Q-PLT-15-1 п. 4): выбор активного коллеги; повтор сохранения уходит в CRM с
 * `transfer_to_user_id`. Коллеги — из списка Оргструктуры (он уже загружен на странице). Выбор — antd `Select` с подписью
 * `label for` и поиском при длинном списке (UX-2a).
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
      <Select<string>
        id={id}
        style={{ width: "100%" }}
        value={value ?? undefined}
        placeholder={t("admin.org.transfer.placeholder")}
        showSearch={colleagues.length > 7}
        optionFilterProp="label"
        loading={list.isPending}
        options={colleagues.map((e) => ({ value: e.id, label: e.name }))}
        onChange={(next) => {
          onChange(next);
        }}
      />
    </div>
  );
}
