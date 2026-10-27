import { Layout, theme } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { CollapseLeftIcon } from "./icons";
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
}

/** Заголовок 56 px, пункты 40 px с бейджами, внизу главное действие (docs/architecture/platform-frontend.md §4, зона 2). */
export function ModuleMenuContent({
  title,
  items,
  labels,
  action,
  onCollapse,
  onNavigate,
}: ModuleMenuContentProps) {
  const { token } = theme.useToken();
  return (
    <nav
      aria-label={labels.nav}
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
        <span style={{ fontWeight: 600 }}>{title}</span>
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
      <ul className="pf-menu-list">
        {items.map((item) => (
          <li key={item.key}>
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
          </li>
        ))}
      </ul>
      <div style={{ flex: 1 }} />
      {action}
    </nav>
  );
}

/** Подменю 208 px; свёрнутое — 0 px, содержимое не рендерится (не попадает в таб-порядок). */
export function ModuleMenu({ open, ...content }: ModuleMenuContentProps & { open: boolean }) {
  return (
    <Layout.Sider
      width={208}
      collapsedWidth={0}
      collapsed={!open}
      trigger={null}
      theme="light"
      role="presentation"
      style={{ borderRight: open ? "1px solid #f0f0f0" : "none" }}
    >
      {open ? <ModuleMenuContent {...content} /> : null}
    </Layout.Sider>
  );
}
