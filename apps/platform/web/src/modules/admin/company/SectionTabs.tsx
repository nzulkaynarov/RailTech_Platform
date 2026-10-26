import { type KeyboardEvent, type ReactNode, useId, useRef } from "react";

export interface SectionTab {
  key: string;
  label: string;
}

/**
 * Вкладки настроек: роль `tablist` с «блуждающим» `tabindex` (стрелки, Home, End), панель — `tabpanel`. Свои, а не `Tabs`
 * antd: на узком экране antd прячет лишние вкладки в меню «ещё» внутрь `tablist`, и разметка перестаёт быть списком вкладок
 * (axe `aria-required-children`). Лента вкладок прокручивается по горизонтали; в ней всегда есть фокусируемые кнопки.
 */
export function SectionTabs({
  label,
  tabs,
  active,
  onChange,
  children,
}: {
  label: string;
  tabs: readonly SectionTab[];
  active: string;
  onChange: (key: string) => void;
  children: ReactNode;
}) {
  const id = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = tabs.length - 1;
    const next =
      event.key === "ArrowRight"
        ? index === last
          ? 0
          : index + 1
        : event.key === "ArrowLeft"
          ? index === 0
            ? last
            : index - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (next === null) return;
    event.preventDefault();
    const tab = tabs[next];
    if (!tab) return;
    onChange(tab.key);
    refs.current[tab.key]?.focus();
  };

  return (
    <>
      <div className="pf-co-tabs" role="tablist" aria-label={label}>
        {tabs.map((tab, index) => {
          const selected = tab.key === active;
          return (
            <button
              key={tab.key}
              ref={(element) => {
                refs.current[tab.key] = element;
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${tab.key}`}
              aria-selected={selected}
              aria-controls={`${id}-panel`}
              tabIndex={selected ? 0 : -1}
              className="pf-co-tab pf-focusable"
              onClick={() => {
                onChange(tab.key);
              }}
              onKeyDown={(event) => {
                move(event, index);
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${active}`}>
        {children}
      </div>
    </>
  );
}
