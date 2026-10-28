import { Drawer, Layout, Tabs } from "antd";
import type { ReactNode } from "react";

import { ChevronRightIcon } from "./icons";
import "./shell.css";
import "./ui.css";

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
  withHide = true,
}: ContextPanelProps & { withHide?: boolean }) {
  // Кнопка «›» лежит рядом с `Tabs`, а не в `tabBarExtraContent`: antd вешает `role="tablist"` на всю полосу вместе с
  // дополнительным содержимым, а внутри `tablist` допустимы только вкладки (axe: aria-required-children). Содержимое
  // отдаём активной панели antd: свой `tabpanel` рядом с ней дублировал бы id и роль.
  return (
    <div className="pf-panel">
      <Tabs
        id={`${id}-tabs`}
        className="pf-panel-tabs"
        activeKey={activeTab}
        onChange={onTabChange}
        tabBarStyle={{ margin: 0, padding: "0 44px 0 16px" }}
        items={tabs.map((tab) => ({
          key: tab.key,
          label: tab.label,
          children: tab.key === activeTab ? <div style={{ padding: 16 }}>{children}</div> : null,
        }))}
      />
      {withHide ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable pf-panel-hide"
          aria-label={hideLabel}
          onClick={onHide}
          style={{ width: 28, height: 28 }}
        >
          <ChevronRightIcon />
        </button>
      ) : null}
    </div>
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

/**
 * < 768 px для разделов с `sheetOnMobile` (B-020): боковое окно — лист на весь экран снизу с заголовком и кнопкой
 * «Закрыть» (UX-оценка P0-4: на телефоне окно справа узкое и закрывает основное наполовину). Вкладки — те же.
 */
export function ContextPanelSheet({
  open,
  onClose,
  title,
  closeLabel,
  ...props
}: ContextPanelProps & {
  open: boolean;
  onClose: () => void;
  /** Заголовок листа: подпись активной вкладки или объекта («Задание · ЗВ-2026-104») */
  title: string;
  /** Подпись кнопки закрытия: «Закрыть» */
  closeLabel: string;
}) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="bottom"
      height="100%"
      closeIcon={null}
      title={title}
      extra={
        <button type="button" className="pf-sheet-close pf-focusable" onClick={onClose}>
          {closeLabel}
        </button>
      }
      styles={{ body: { padding: 0 }, header: { padding: "12px 16px" } }}
      aria-label={props.label}
      id={props.id}
      className="pf-panel-sheet"
    >
      <PanelBody {...props} withHide={false} />
    </Drawer>
  );
}
