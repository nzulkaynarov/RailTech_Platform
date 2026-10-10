import { Grid, Menu, Select } from "antd";

import { sectionGroups } from "../../domain/settingsLayout";
import { t } from "../../i18n/ru";

type Props = { sections: string[]; current: string; onSelect: (section: string) => void };

const sectionLabel = (key: string) => t.settings.keys[key] ?? key;
const groupLabel = (key: string) => t.settings.groups[key] ?? key;

/**
 * Навигация по разделам настроек: слева списком с группами (desktop), на мобильном —
 * выпадающий список. Вместо 11 горизонтальных вкладок, часть которых пряталась за «⋯».
 */
export function SettingsNav({ sections, current, onSelect }: Props) {
  const screens = Grid.useBreakpoint();
  const groups = sectionGroups(sections);
  if (screens.md === false) {
    return (
      <Select
        aria-label={t.settings.section}
        className="settings-nav-select"
        value={current}
        onChange={onSelect}
        options={groups.map((g) => ({
          label: groupLabel(g.key),
          title: groupLabel(g.key),
          options: g.sections.map((s) => ({ value: s, label: sectionLabel(s) })),
        }))}
      />
    );
  }
  return (
    <nav aria-label={t.settings.sections} className="settings-nav">
      <Menu
        mode="inline"
        selectedKeys={[current]}
        onClick={({ key }) => {
          onSelect(key);
        }}
        items={groups.map((g) => ({
          type: "group" as const,
          key: `group-${g.key}`,
          label: groupLabel(g.key),
          children: g.sections.map((s) => ({ key: s, label: sectionLabel(s) })),
        }))}
      />
    </nav>
  );
}
