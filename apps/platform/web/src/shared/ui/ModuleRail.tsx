import { Layout } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { MODULE_ICONS } from "./moduleIcons";
import "./shell.css";

export interface RailModule {
  code: keyof typeof MODULE_ICONS;
  name: string;
  to: string;
  active: boolean;
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
}

function RailLink({ module }: { module: RailModule }) {
  const Icon = MODULE_ICONS[module.code];
  return (
    <Link
      to={module.to}
      className="pf-rail-btn pf-focusable"
      aria-current={module.active ? "page" : undefined}
    >
      <Icon />
      <span>{module.name}</span>
    </Link>
  );
}

/**
 * Рейл модулей (03-frontend.md §4, зона 1): 64 px, логотип 36×36, кнопки 56×56, внизу аватар и роль.
 * Модули вне роли в `modules` не приходят и не рендерятся. На экранах < 768 — нижняя панель.
 */
export function ModuleRail({
  modules,
  label,
  logoLabel,
  logoTo,
  profile,
  variant = "side",
}: ModuleRailProps) {
  if (variant === "bottom") {
    return (
      <nav aria-label={label} className="pf-bottom-bar">
        {modules.map((m) => (
          <RailLink key={m.code} module={m} />
        ))}
        <div style={{ flex: "0 0 auto", padding: "0 4px" }}>{profile}</div>
      </nav>
    );
  }
  return (
    <Layout.Sider
      width={64}
      theme="light"
      role="presentation"
      style={{ borderRight: "1px solid #f0f0f0", overflow: "visible" }}
    >
      <nav
        aria-label={label}
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
          <RailLink key={m.code} module={m} />
        ))}
        <div style={{ flex: 1 }} />
        {profile}
      </nav>
    </Layout.Sider>
  );
}
