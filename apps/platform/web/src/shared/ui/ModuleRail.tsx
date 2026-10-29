import { Layout, Popover } from "antd";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { MODULE_ICONS } from "./moduleIcons";
import "./shell.css";

export interface RailSubmenuItem {
  key: string;
  path: string;
  label: string;
  active?: boolean;
  badge?: {
    count: number;
    attention: boolean;
    hint?: string;
  };
}

export interface RailModule {
  code: keyof typeof MODULE_ICONS;
  name: string;
  title?: string;
  to: string;
  active: boolean;
  sections?: readonly RailSubmenuItem[];
}

export interface ModuleRailProps {
  modules: readonly RailModule[];
  /** Подпись для навигации и логотипа */
  label: string;
  logoLabel: string;
  logoTo: string;
  /** Меню аватара с ролью под ним (низ рейла) */
  profile: ReactNode;
  /** `bottom` — нижняя панель на экранах < 768 */
  variant?: "side" | "bottom";
  /** Открыто ли меню модуля на десктопе */
  menuOpen?: boolean;
}

function RailLink({ module, onClick }: { module: RailModule; onClick?: () => void }) {
  const Icon = MODULE_ICONS[module.code];
  return (
    <Link
      to={module.to}
      onClick={onClick}
      className="pf-rail-btn pf-focusable"
      aria-current={module.active ? "page" : undefined}
    >
      <Icon />
      <span>{module.name}</span>
    </Link>
  );
}

function RailItemWithFlyout({ module, menuOpen }: { module: RailModule; menuOpen?: boolean }) {
  const [open, setOpen] = useState(false);
  const canShowFlyout =
    (!menuOpen || !module.active) && !!module.sections && module.sections.length > 0;

  if (!canShowFlyout) {
    return <RailLink module={module} />;
  }

  const content = (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        style={{
          fontWeight: 600,
          fontSize: 13,
          padding: "4px 8px 6px",
          borderBottom: "1px solid #f0f0f0",
          marginBottom: 4,
          color: "#1f1f1f",
        }}
      >
        {module.title ?? module.name}
      </div>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 2,
        }}
      >
        {module.sections?.map((sec) => (
          <li key={sec.key}>
            <Link
              to={sec.path}
              onClick={() => {
                setOpen(false);
              }}
              className="pf-menu-item pf-focusable"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "6px 8px",
                borderRadius: 4,
                fontSize: 13,
                textDecoration: "none",
                color: sec.active ? "#0958d9" : "#334155",
                background: sec.active ? "#e6f4ff" : "transparent",
              }}
            >
              <span>{sec.label}</span>
              {sec.badge && sec.badge.count > 0 ? (
                <span
                  className={sec.badge.attention ? "pf-badge" : "pf-badge pf-badge--quiet"}
                  title={sec.badge.hint}
                >
                  {sec.badge.count}
                </span>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <Popover
      placement="rightTop"
      trigger="hover"
      mouseEnterDelay={0.12}
      mouseLeaveDelay={0.15}
      styles={{ body: { padding: 8, width: 232 } }}
      content={content}
      open={open}
      onOpenChange={setOpen}
    >
      <div>
        <RailLink
          module={module}
          onClick={() => {
            setOpen(false);
          }}
        />
      </div>
    </Popover>
  );
}

/**
 * Рейл модулей (docs/architecture/platform-frontend.md §4, зона 1): 56 px на десктопе, логотип 36×36, кнопки 48×52, внизу аватар и роль.
 * Модули вне роли в `modules` не приходят и не рендерятся. На экранах < 768 — нижняя панель.
 */
export function ModuleRail({
  modules,
  label,
  logoLabel,
  logoTo,
  profile,
  variant = "side",
  menuOpen = true,
}: ModuleRailProps) {
  if (variant === "bottom") {
    return (
      <nav aria-label={label} className="pf-bottom-bar" data-tour="rail">
        {modules.map((m) => (
          <RailLink key={m.code} module={m} />
        ))}
        <div style={{ flex: "0 0 auto", padding: "0 4px" }}>{profile}</div>
      </nav>
    );
  }
  return (
    <Layout.Sider
      width={56}
      theme="light"
      role="presentation"
      style={{ borderRight: "1px solid #f0f0f0", overflow: "visible" }}
    >
      <nav
        aria-label={label}
        data-tour="rail"
        style={{
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 4,
          padding: "8px 0 12px",
        }}
      >
        <Link
          to={logoTo}
          aria-label={logoLabel}
          className="pf-focusable"
          style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            background: "#1668dc",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 13,
            marginBottom: 12,
            textDecoration: "none",
          }}
        >
          RT
        </Link>
        {modules.map((m) => (
          <RailItemWithFlyout key={m.code} module={m} menuOpen={menuOpen} />
        ))}
        <div style={{ flex: 1 }} />
        {profile}
      </nav>
    </Layout.Sider>
  );
}
