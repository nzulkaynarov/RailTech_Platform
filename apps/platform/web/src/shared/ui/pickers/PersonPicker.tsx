import { Select } from "antd";
import { useTranslation } from "react-i18next";

import type { CounterpartyPersonPick } from "../../api/generated/model";
import { useListCounterpartyPickerPeople } from "../../api/generated/platform-bff";

import "./pickers.css";

export type PickedPerson = CounterpartyPersonPick;

/**
 * Поле выбора человека компании (ЕД-6): люди выбранной компании — имя, должность, почта; главный контакт первым.
 * Без компании поле выключено. Выбор заполняет зависимое (почту, «Кому») в форме через `onChange`.
 */
export function PersonPicker({
  id,
  companyId,
  value,
  onChange,
  describedBy,
  placeholder,
}: {
  id: string;
  /** Id компании; пусто — поле выключено */
  companyId: string;
  value: string;
  onChange: (person: PickedPerson | null) => void;
  describedBy?: string;
  placeholder?: string;
}) {
  const { t } = useTranslation("ui");
  const people = useListCounterpartyPickerPeople(companyId, {
    query: { enabled: companyId !== "", staleTime: 30_000, retry: false },
  });
  const items = companyId ? (people.data?.items ?? []) : [];
  return (
    <Select<string>
      id={id}
      showSearch
      allowClear
      optionFilterProp="text"
      disabled={companyId === ""}
      loading={people.isFetching}
      value={value || undefined}
      placeholder={placeholder ?? t("picker.person.placeholder")}
      notFoundContent={t("picker.person.empty")}
      aria-describedby={describedBy}
      optionLabelProp="text"
      options={items.map((person) => ({
        value: person.id,
        text: person.name,
        title: person.name,
        label: (
          <span className="pf-pick-row">
            <span className="pf-pick-row__name">{person.name}</span>
            <span className="pf-pick-row__sub">
              {[person.position, person.email].filter(Boolean).join(" · ")}
            </span>
          </span>
        ),
      }))}
      onChange={(next: string | undefined) => {
        onChange(items.find((person) => person.id === next) ?? null);
      }}
    />
  );
}
