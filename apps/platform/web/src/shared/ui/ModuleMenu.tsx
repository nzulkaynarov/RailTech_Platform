import { theme } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { CollapseLeftIcon, SettingsIcon } from "./icons";
import "./shell.css";

export interface MenuBadge {
  count: number;
  /** true — красный бейдж «требует действия», false — серый счётчик */
  attention: boolean;
  /** Подсказка вместо «требует действия»: у раздела-заглушки число считает старая система («ещё в старой системе: 1») */
  hint?: string;
}

export interface MenuItem {
  key: string;
  to: string;
  label: string;
  active: boolean;
  badge?: MenuBadge;
  /** Заголовок группы (Настройки, SET-IA): пункты с одной группой идут подряд под её заголовком */
  group?: string | undefined;
}

export interface ModuleMenuLabels {
  nav: string;
  collapse: string;
  needsAction: string;
}

export interface ModuleMenuContentProps {
  /** «1. Dashboard» */
  title: string;
  items: readonly MenuItem[];
  labels: ModuleMenuLabels;
  /** Главное действие модуля — primary-кнопка на всю ширину внизу */
  action?: ReactNode;
  /** Кнопка «‹‹» в заголовке: свернуть (desktop) или закрыть (Drawer) */
  onCollapse: () => void;
  /** Вызывается при переходе по пункту (закрыть Drawer) */
  onNavigate?: () => void;
  /** ⚙ в заголовке: своя группа Настроек модуля (SET-IA, HubSpot) */
  settings?: { to: string; label: string };
}

/** Пункты подряд по группам: заголовок группы — перед первым её пунктом. */
function groupedItems(
  items: readonly MenuItem[],
): { group: string | undefined; items: MenuItem[] }[] {
  const out: { group: string | undefined; items: MenuItem[] }[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (last && last.group === item.group) last.items.push(item);
    else out.push({ group: item.group, items: [item] });
  }
  return out;
}

function MenuLink({
  item,
  labels,
  onNavigate,
}: {
  item: MenuItem;
  labels: ModuleMenuLabels;
  onNavigate?: (() => void) | undefined;
}) {
  return (
    <Link
      to={item.to}
      className="pf-menu-item pf-focusable"
      aria-current={item.active ? "page" : undefined}
      onClick={onNavigate}
    >
      <span>{item.label}</span>
      {item.badge ? (
        <>
          <span
            className={item.badge.attention ? "pf-badge" : "pf-badge pf-badge--quiet"}
            title={item.badge.hint}
            aria-hidden="true"
          >
            {item.badge.count}
          </span>
          <span className="pf-sr-only">
            {item.badge.hint
              ? `${String(item.badge.count)}, ${item.badge.hint}`
              : item.badge.attention
                ? `${String(item.badge.count)}, ${labels.needsAction}`
                : String(item.badge.count)}
          </span>
        </>
      ) : null}
    </Link>
  );
}

/** Заголовок 56 px, пункты 40 px с бейджами, внизу главное действие (docs/architecture/platform-frontend.md §4, зона 2). */
export function ModuleMenuContent({
  title,
  items,
  labels,
  action,
  onCollapse,
  onNavigate,
  settings,
}: ModuleMenuContentProps) {
  const { token } = theme.useToken();
  return (
    <nav
      aria-label={labels.nav}
      data-tour="menu"
      style={{ height: "100%", display: "flex", flexDirection: "column", padding: "0 8px 12px" }}
    >
      <div
        style={{
          height: 56,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: `1px solid ${token.colorSplit}`,
          margin: "0 -8px 8px",
          padding: "0 12px 0 16px",
          flex: "0 0 auto",
        }}
      >
        <span style={{ fontWeight: 600, flex: 1, minWidth: 0 }}>{title}</span>
        {settings ? (
          <Link
            to={settings.to}
            aria-label={settings.label}
            title={settings.label}
            className="pf-icon-btn pf-focusable"
            style={{ width: 28, height: 28 }}
            onClick={onNavigate}
          >
            <SettingsIcon />
          </Link>
        ) : null}
        <button
          type="button"
          aria-label={labels.collapse}
          onClick={onCollapse}
          className="pf-icon-btn pf-focusable"
          style={{ width: 28, height: 28 }}
        >
          <CollapseLeftIcon />
        </button>
      </div>
      {items.some((item) => item.group) ? (
        <div className="pf-menu-groups">
          {groupedItems(items).map((block, index) =>
            block.group ? (
              <div key={block.group} role="group" aria-labelledby={`pf-menu-g-${String(index)}`}>
                <p className="pf-menu-group" id={`pf-menu-g-${String(index)}`}>
                  {block.group}
                </p>
                <ul className="pf-menu-list pf-menu-list--grouped">
                  {block.items.map((item) => (
                    <li key={item.key}>
                      <MenuLink item={item} labels={labels} onNavigate={onNavigate} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <ul key={`top-${String(index)}`} className="pf-menu-list pf-menu-list--grouped">
                {block.items.map((item) => (
                  <li key={item.key}>
                    <MenuLink item={item} labels={labels} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            ),
          )}
        </div>
      ) : (
        <ul className="pf-menu-list">
          {items.map((item) => (
            <li key={item.key}>
              <MenuLink item={item} labels={labels} onNavigate={onNavigate} />
            </li>
          ))}
        </ul>
      )}
      <div style={{ flex: 1 }} />
      {action}
    </nav>
  );
}

/** Ширина раскрытого подменю (platform-frontend.md §4, зона 2) */
const MENU_WIDTH = 208;

/**
 * Подменю 208 px; свёрнутое не рендерится (не занимает места и не попадает в таб-порядок). Ширина меняется одним шагом,
 * в одном кадре (UX-1a, аудит S3): у antd `Sider` — `transition` ширины (13–15 кадров перекладки основного окна) и
 * внутреннее состояние `collapsed`, которое догоняет проп на кадр позже. Поэтому — простая колонка.
 */
export function ModuleMenu({ open, ...content }: ModuleMenuContentProps & { open: boolean }) {
  if (!open) return null;
  return (
    <div
      role="presentation"
      style={{
        flex: `0 0 ${String(MENU_WIDTH)}px`,
        width: MENU_WIDTH,
        minWidth: MENU_WIDTH,
        maxWidth: MENU_WIDTH,
        boxSizing: "border-box",
        background: "#fff",
        borderRight: "1px solid #f0f0f0",
        overflow: "hidden",
      }}
    >
      <ModuleMenuContent {...content} />
    </div>
  );
}
