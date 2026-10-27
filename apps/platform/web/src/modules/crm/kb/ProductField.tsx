import { Input, Select } from "antd";
import { useTranslation } from "react-i18next";

import { useListKbProducts } from "../../../shared/api/generated/platform-bff";
import { FormField } from "../../../shared/ui/FormParts";
import { productKeyValid } from "./refresh";

/**
 * Продукт документа. Справочник продуктов CRM читает только роль с правом `leads:read`: у администратора без второй роли
 * CRM отвечает 403 — тогда ключ продукта вводится вручную (латиница, цифры, дефис; пусто — документ про компанию).
 */
export function ProductField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation("kb");
  const products = useListKbProducts({ query: { retry: false } });
  const items = products.data?.items;
  const invalid = !productKeyValid(value);
  return (
    <FormField
      id={id}
      label={t("fields.product")}
      hint={items ? t("fields.productHint") : t("fields.productKeyHint")}
    >
      {items ? (
        <Select
          id={id}
          allowClear
          value={value === "" ? undefined : value}
          placeholder={t("fields.noProduct")}
          options={items
            .filter((p) => p.is_active)
            .map((p) => ({ value: p.key, label: `${p.name} (${p.key})` }))}
          onChange={(next: string | undefined) => {
            onChange(next ?? "");
          }}
        />
      ) : (
        <Input
          id={id}
          value={value}
          status={invalid ? "error" : undefined}
          aria-invalid={invalid || undefined}
          autoComplete="off"
          onChange={(event) => {
            onChange(event.target.value.trim());
          }}
        />
      )}
    </FormField>
  );
}
