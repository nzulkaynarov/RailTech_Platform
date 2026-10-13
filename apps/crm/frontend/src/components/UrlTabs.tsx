import { Collapse, Grid, Tabs } from "antd";
import type { ReactNode } from "react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { resolveTab } from "../domain/urlTabs";

export type UrlTab = { key: string; label: ReactNode; children: ReactNode };

/**
 * Разделы страницы, выбранный — в `?tab=` (UX волна 3). На телефоне вкладки не помещаются, и
 * antd прячет лишние за кнопку «ещё» внутри `tablist` (axe aria-required-children), поэтому там
 * те же разделы — раскрывающимся списком (`Collapse`, один открыт).
 */
export function UrlTabs({ items, label }: { items: UrlTab[]; label: string }) {
  const [search, setSearch] = useSearchParams();
  const [closed, setClosed] = useState(false);
  const phone = Grid.useBreakpoint().md === false;
  const active = resolveTab(
    search.get("tab"),
    items.map((tab) => tab.key),
  );
  const select = (tab: string | undefined) => {
    setClosed(!tab);
    if (tab) setSearch({ tab }, { replace: true });
  };
  if (phone) {
    // Не `accordion`: он ставит role="tablist" на список панелей (тот же axe). Один открытый
    // раздел держим сами — новый ключ из `keys` заменяет текущий.
    const open = closed ? [] : [active];
    return (
      <Collapse
        size="small"
        activeKey={open}
        onChange={(keys) => {
          select(keys.find((key) => !open.includes(key)));
        }}
        items={items}
      />
    );
  }
  return <Tabs aria-label={label} activeKey={active} onChange={select} items={items} />;
}
