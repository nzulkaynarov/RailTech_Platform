import { Select } from "antd";
import { Link } from "react-router";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import { FormField } from "../../../shared/ui/FormParts";
import { type SectionGroup } from "./sections";

interface Props {
  groups: readonly SectionGroup[];
  current: string;
  /** Адрес раздела: сохраняет прочие параметры экрана, кроме относящихся к панели. */
  hrefOf: (section: string) => string;
  onSelect: (section: string) => void;
}

/** Разделы экрана: на широком — список со ссылками по группам, на узком — выпадающий список. */
export function BotNav({ groups, current, hrefOf, onSelect }: Props) {
  const { t } = useTranslation("bot");
  const { mobile } = useViewport();
  const label = (key: string) => t(`keys.${key}`, { defaultValue: key });
  const extra = [
    {
      key: "extra",
      sections: ["templates", "exports"],
    },
  ];
  const all = [...groups, ...extra];
  const groupLabel = (key: string) => t(`groups.${key}`, { defaultValue: key });
  const itemLabel = (key: string) =>
    key === "templates" || key === "exports" ? t(`nav.${key}`) : label(key);
  if (mobile) {
    return (
      <FormField id="bot-section" label={t("nav.section")}>
        <Select
          id="bot-section"
          value={current}
          onChange={onSelect}
          options={all.map((g) => ({
            label: groupLabel(g.key),
            title: groupLabel(g.key),
            options: g.sections.map((s) => ({ value: s, label: itemLabel(s) })),
          }))}
        />
      </FormField>
    );
  }
  return (
    <nav aria-label={t("nav.sections")} className="pf-bot-nav">
      {all.map((group) => (
        <div key={group.key} className="pf-bot-nav-group">
          <p className="pf-bot-nav-title" id={`bot-nav-${group.key}`}>
            {groupLabel(group.key)}
          </p>
          <ul aria-labelledby={`bot-nav-${group.key}`}>
            {group.sections.map((section) => (
              <li key={section}>
                <Link
                  className="pf-focusable pf-bot-nav-link"
                  to={hrefOf(section)}
                  aria-current={section === current ? "page" : undefined}
                >
                  {itemLabel(section)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
