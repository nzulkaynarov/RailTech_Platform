import { Select } from "antd";
import { Link } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import { FormField } from "../../../shared/ui/FormParts";

import "../bot/bot.css";

export interface NavGroup {
  key: string;
  label: string;
  items: readonly { key: string; label: string }[];
}

/**
 * Список частей страницы слева, по разделам (SET-IA, «Справочники»: Продажи · Документы · Расчёт). Один уровень: пункт открывает
 * часть справа, вкладок внутри нет. На телефоне — выпадающий список с подписью.
 */
export function SettingsNav({
  label,
  groups,
  current,
  hrefOf,
  onSelect,
}: {
  label: string;
  groups: readonly NavGroup[];
  current: string;
  hrefOf: (key: string) => string;
  onSelect: (key: string) => void;
}) {
  const { mobile } = useViewport();
  if (mobile) {
    return (
      <FormField id="pf-set-nav" label={label}>
        <Select
          id="pf-set-nav"
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
  return (
    <nav aria-label={label} className="pf-bot-nav">
      {groups.map((group) => (
        <div key={group.key} className="pf-bot-nav-group">
          <p className="pf-bot-nav-title" id={`pf-set-nav-${group.key}`}>
            {group.label}
          </p>
          <ul aria-labelledby={`pf-set-nav-${group.key}`}>
            {group.items.map((item) => (
              <li key={item.key}>
                <Link
                  className="pf-focusable pf-bot-nav-link"
                  to={hrefOf(item.key)}
                  aria-current={item.key === current ? "page" : undefined}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
