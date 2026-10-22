import { Drawer, Layout, Tabs } from "antd";
import type { ReactNode } from "react";

import { ChevronRightIcon } from "./icons";
import "./shell.css";

export interface ContextTab {
  key: string;
  label: string;
}

export interface ContextPanelProps {
  id: string;
  /** Имя области для скринридера: «Боковое окно» */
  label: string;
  tabs: readonly ContextTab[];
  activeTab: string;
  onTabChange: (key: string) => void;
  /** Подпись кнопки «›»: «Скрыть боковое окно» */
  hideLabel: string;
  onHide: () => void;
  /** Содержимое активной вкладки */
  children: ReactNode;
}

function PanelBody({
  id,
  tabs,
  activeTab,
  onTabChange,
  hideLabel,
  onHide,
  children,
}: ContextPanelProps) {
  // Кнопка «›» — вне `tablist` (внутри него допустимы только вкладки, иначе axe: aria-required-children).
  const tabsId = `${id}-tabs`;
  return (
    <>
      <div
        className="pf-panel-tabs"
        style={{
          display: "flex",
          alignItems: "center",
          padding: "0 8px 0 16px",
          borderBottom: "1px solid #f0f0f0",
        }}
      >
        <Tabs
          id={tabsId}
          activeKey={activeTab}
          onChange={onTabChange}
          style={{ flex: 1, minWidth: 0 }}
          tabBarStyle={{ margin: 0 }}
          items={tabs.map((tab) => ({ key: tab.key, label: tab.label }))}
        />
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={hideLabel}
          onClick={onHide}
          style={{ width: 28, height: 28, flex: "0 0 auto" }}
        >
          <ChevronRightIcon />
        </button>
      </div>
      <div
        role="tabpanel"
        id={`${tabsId}-panel-${activeTab}`}
        aria-labelledby={`${tabsId}-tab-${activeTab}`}
        style={{ padding: 16 }}
      >
        {children}
      </div>
    </>
  );
}

/** Боковое окно 360 px справа, сворачивается до 0 (≥ 1200 px). Свёрнутое — не рендерится. */
export function ContextPanel({ open, ...props }: ContextPanelProps & { open: boolean }) {
  return (
    <Layout.Sider
      id={props.id}
      aria-label={open ? props.label : undefined}
      aria-hidden={!open}
      width={360}
      collapsedWidth={0}
      collapsed={!open}
      trigger={null}
      theme="light"
      style={{ borderLeft: open ? "1px solid #f0f0f0" : "none", overflow: "auto" }}
    >
      {open ? <PanelBody {...props} /> : null}
    </Layout.Sider>
  );
}

/** < 1200 px: боковое окно — `Drawer` без затемнения поверх основного (между шапкой и нижней панелью). */
export function ContextPanelDrawer({
  open,
  onClose,
  offsetTop,
  offsetBottom,
  ...props
}: ContextPanelProps & {
  open: boolean;
  onClose: () => void;
  offsetTop: number;
  offsetBottom: number;
}) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      mask={false}
      closable={false}
      keyboard
      width={360}
      placement="right"
      rootStyle={{ top: offsetTop, bottom: offsetBottom, height: "auto" }}
      styles={{
        body: { padding: 0 },
        wrapper: { maxWidth: "100vw", boxShadow: "none", borderLeft: "1px solid #f0f0f0" },
      }}
      aria-label={props.label}
      id={props.id}
    >
      <PanelBody {...props} />
    </Drawer>
  );
}
