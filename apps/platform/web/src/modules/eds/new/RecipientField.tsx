import { AutoComplete } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useSearchEdsAddressees } from "../../../shared/api/generated/platform-bff";
import type { EdsAddressee } from "../../../shared/api/generated/model";

/** Сколько букв нужно, чтобы искать по контрагентам (как в контракте `GET /eds/addressees`) */
const MIN_QUERY = 2;

/**
 * «Организация» письма (пункт «Ш»): ввод с подсказками из контрагентов — клиентов и партнёров ERP по названию или ИНН.
 * Выбор подставляет ИНН, почту и «Кому» организации; можно писать и вручную — адресата нет в книге. ERP не ответила —
 * подсказок нет, поле работает как обычное.
 */
export function RecipientField({
  id,
  value,
  onChange,
  onPick,
  describedBy,
  invalid,
}: {
  id: string;
  value: string;
  onChange: (name: string) => void;
  onPick: (addressee: EdsAddressee) => void;
  describedBy: string | undefined;
  invalid: boolean;
}) {
  const { t } = useTranslation("documents");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(value.trim());
    }, 250);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value]);
  const enabled = query.length >= MIN_QUERY;
  const found = useSearchEdsAddressees(
    { q: query },
    { query: { enabled, staleTime: 30_000, retry: false } },
  );
  const items = enabled ? (found.data?.items ?? []) : [];
  return (
    <AutoComplete
      id={id}
      value={value}
      maxLength={255}
      status={invalid ? "error" : undefined}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      placeholder={t("form.recipient.placeholder")}
      // выбор подсказки приходит и сюда — со значением id; название ставит onPick
      onChange={(next: string) => {
        if (!items.some((item) => item.id === next)) onChange(next);
      }}
      onSelect={(picked: string) => {
        const addressee = items.find((item) => item.id === picked);
        if (addressee) onPick(addressee);
      }}
      options={items.map((item) => ({
        value: item.id,
        label: (
          <span>
            {item.name}
            {item.inn ? (
              <span className="pf-hint"> · {t("form.recipient.innShort", { inn: item.inn })}</span>
            ) : null}
          </span>
        ),
      }))}
    />
  );
}
