import { Select } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useListEdsDealOptions } from "../../../shared/api/generated/platform-bff";
import type { DealChoice } from "./formModel";

/**
 * «Связь с проектом»: поиск заявки или проекта по номеру, названию или компании (ERP, `GET /eds/deal-options`). Поле
 * необязательно; ERP не ответила — подсказка вместо списка, остальная форма работает.
 */
export function DealField({
  id,
  value,
  onChange,
  describedBy,
  invalid,
}: {
  id: string;
  value: DealChoice | null;
  onChange: (choice: DealChoice | null) => void;
  describedBy: string;
  invalid: boolean;
}) {
  const { t } = useTranslation("documents");
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(typed.trim());
    }, 250);
    return () => {
      window.clearTimeout(timer);
    };
  }, [typed]);
  const options = useListEdsDealOptions(query ? { q: query } : undefined, {
    query: { staleTime: 30_000 },
  });
  const unavailable = options.data?.sources.erp === "unavailable";
  return (
    <Select<{ value: number; label: string }>
      id={id}
      showSearch
      allowClear
      labelInValue
      filterOption={false}
      placeholder={t("form.deal.placeholder")}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      value={value ? { value: value.erp_deal_id, label: value.label } : undefined}
      onSearch={setTyped}
      onChange={(choice: { value: number; label: string } | undefined) => {
        setTyped("");
        onChange(choice ? { erp_deal_id: choice.value, label: choice.label } : null);
      }}
      notFoundContent={
        options.isFetching
          ? t("form.deal.searching")
          : unavailable
            ? t("form.deal.unavailable")
            : t("form.deal.empty")
      }
      options={(options.data?.items ?? []).map((item) => ({
        value: item.erp_deal_id,
        label: [item.number, item.title, item.company].filter(Boolean).join(" · "),
      }))}
    />
  );
}
