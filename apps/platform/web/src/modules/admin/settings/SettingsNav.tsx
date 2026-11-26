import { Select } from "antd";

import { FormField } from "../../../shared/ui/FormParts";

export interface NavGroup {
  key: string;
  label: string;
  items: readonly { key: string; label: string }[];
}

/**
 * Выбор части страницы по разделам («Справочники»: Продажи · Документы · Расчёт). НАСТ-1: второго левого списка внутри страницы
 * нет — меню Настроек одно (в оболочке), часть страницы выбирается списком над содержимым при любой ширине.
 */
export function SettingsNav({
  label,
  groups,
  current,
  onSelect,
}: {
  label: string;
  groups: readonly NavGroup[];
  current: string;
  onSelect: (key: string) => void;
}) {
  return (
    <FormField id="pf-set-nav" label={label}>
      <Select
        id="pf-set-nav"
        showSearch
        virtual={false}
        optionFilterProp="label"
        value={current}
        onChange={onSelect}
        options={groups.map((group) => ({
          label: group.label,
          title: group.label,
          options: group.items.map((item) => ({ value: item.key, label: item.label })),
        }))}
      />
    </FormField>
  );
}
