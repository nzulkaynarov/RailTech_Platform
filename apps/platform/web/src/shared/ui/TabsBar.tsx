import { Tabs, type TabsProps } from "antd";
import type { ReactNode } from "react";

import "./data-block.css";

/**
 * Вкладки-фильтр списка (UX-1c, S8): полоса antd `Tabs` без своих панелей и одна панель (`tabpanel`) под ней. Тело
 * списка при смене вкладки не переезжает в другую панель и не размонтируется: таблица остаётся на месте с прежними
 * строками, пока грузятся новые. `id` — основа id вкладок antd (`<id>-tab-<ключ>`), на него ссылается панель.
 */
export function TabsBar({
  id,
  label,
  activeKey,
  items,
  onChange,
  tabBarStyle,
  children,
}: {
  id: string;
  label: string;
  activeKey: string;
  items: readonly { key: string; label: ReactNode }[];
  onChange: (key: string) => void;
  tabBarStyle?: TabsProps["tabBarStyle"];
  children: ReactNode;
}) {
  return (
    <>
      <Tabs
        id={id}
        className="pf-tabs-bar"
        aria-label={label}
        activeKey={activeKey}
        onChange={onChange}
        tabBarStyle={tabBarStyle}
        items={items.map((item) => ({ key: item.key, label: item.label }))}
      />
      <div role="tabpanel" id={`${id}-body`} aria-labelledby={`${id}-tab-${activeKey}`}>
        {children}
      </div>
    </>
  );
}
