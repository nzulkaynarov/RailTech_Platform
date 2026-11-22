import { Select } from "antd";
import { useMemo } from "react";

import "./EmployeePicker.css";

export interface EmployeeOption {
  id: string;
  name: string;
  position?: string | null;
}

interface Props {
  id: string;
  /** `id` выбранного сотрудника; пусто — не выбран */
  value: string | undefined;
  options: readonly EmployeeOption[];
  /** Выбор или очистка (`undefined`); второй аргумент — выбранная строка, из неё берутся зависимые поля */
  onChange: (id: string | undefined, option?: EmployeeOption) => void;
  loading?: boolean;
  placeholder?: string;
  /** Текст в пустом списке («нет сотрудников с правом подписи») */
  emptyText?: string;
  allowClear?: boolean;
  disabled?: boolean;
  "aria-describedby"?: string;
}

/**
 * Выбор сотрудника из списка (ЕД-6): поиск по имени и должности, в строке — имя и должность. Один компонент для
 * подписанта письма и «Кто замещает»; список готовит экран (подписанты, все активные), поле ничего не вписывает текстом.
 */
export function EmployeePicker({
  id,
  value,
  options,
  onChange,
  loading,
  placeholder,
  emptyText,
  allowClear = true,
  disabled,
  "aria-describedby": describedBy,
}: Props) {
  const byId = useMemo(() => new Map(options.map((o) => [o.id, o])), [options]);
  return (
    <Select
      id={id}
      showSearch
      allowClear={allowClear}
      style={{ width: "100%" }}
      value={value || undefined}
      loading={loading}
      disabled={disabled}
      placeholder={placeholder}
      aria-describedby={describedBy}
      notFoundContent={loading ? undefined : emptyText}
      optionFilterProp="search"
      optionLabelProp="title"
      options={options.map((o) => ({
        value: o.id,
        title: o.name,
        search: `${o.name} ${o.position ?? ""}`,
        label: (
          <span className="pf-emp-option">
            <span>{o.name}</span>
            {o.position ? <span className="pf-emp-position">{o.position}</span> : null}
          </span>
        ),
      }))}
      onChange={(next: string | undefined) => {
        onChange(next || undefined, next ? byId.get(next) : undefined);
      }}
    />
  );
}
