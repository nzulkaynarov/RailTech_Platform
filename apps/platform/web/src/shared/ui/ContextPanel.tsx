import {
  ArrowsAltOutlined,
  PushpinFilled,
  PushpinOutlined,
  ShrinkOutlined,
} from "@ant-design/icons";
import { Drawer, Layout, Tabs } from "antd";
import { useEffect, type ReactNode } from "react";

import type { PanelLayoutMode, PanelWidthPreset } from "../../app/shell/panelsStore";
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
  /** Режим отображения: 'overlay' (slide-over поверх контента) или 'docked' (в сетке) */
  panelMode?: PanelLayoutMode;
  onModeChange?: (mode: PanelLayoutMode) => void;
  /** Ширина: 'default' (440px) или 'wide' (600px) */
  panelWidth?: PanelWidthPreset;
  onWidthChange?: (width: PanelWidthPreset) => void;
  /** Доступен ли режим docked (экран >= 1280px) */
  canDock?: boolean;
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
  panelMode = "overlay",
  onModeChange,
  panelWidth = "default",
  onWidthChange,
  canDock = false,
}: ContextPanelProps & { withHide?: boolean }) {
  // Esc закрывает панель, если поверх не открыто модальное окно или выпадающий список
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        const hasOpenOverlay = document.querySelector(
          '.ant-modal-wrap:not([style*="display: none"]), .ant-select-dropdown:not(.ant-select-dropdown-hidden)',
        );
        if (!hasOpenOverlay) {
          onHide();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onHide]);

  const controls = (
    <div
      style={{
        position: "absolute",
        top: 9,
        right: 8,
        display: "flex",
        alignItems: "center",
        gap: 4,
        zIndex: 1,
      }}
    >
      {onWidthChange ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={panelWidth === "wide" ? "Стандартная ширина" : "Широкая панель"}
          title={panelWidth === "wide" ? "Стандартная ширина (440px)" : "Широкая панель (600px)"}
          onClick={() => {
            onWidthChange(panelWidth === "wide" ? "default" : "wide");
          }}
          style={{ width: 28, height: 28 }}
        >
          {panelWidth === "wide" ? <ShrinkOutlined /> : <ArrowsAltOutlined />}
        </button>
      ) : null}
      {canDock && onModeChange ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={panelMode === "docked" ? "Режим поверх" : "Закрепить в сетке"}
          title={
            panelMode === "docked"
              ? "Режим: В сетке (нажмите для режима Поверх)"
              : "Режим: Поверх (нажмите для закрепления в сетке)"
          }
          onClick={() => {
            onModeChange(panelMode === "docked" ? "overlay" : "docked");
          }}
          style={{ width: 28, height: 28 }}
        >
          {panelMode === "docked" ? (
            <PushpinFilled style={{ color: "#1668dc" }} />
          ) : (
            <PushpinOutlined />
          )}
        </button>
      ) : null}
      {withHide ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable pf-panel-hide"
          aria-label={hideLabel}
          title={hideLabel}
          onClick={onHide}
          style={{ position: "static", width: 28, height: 28 }}
        >
          <ChevronRightIcon />
        </button>
      ) : null}
    </div>
  );

  return (
    <div
      className="pf-panel"
      style={{ position: "relative", height: "100%", display: "flex", flexDirection: "column" }}
    >
      <Tabs
        id={`${id}-tabs`}
        className="pf-panel-tabs"
        activeKey={activeTab}
        onChange={onTabChange}
        tabBarStyle={{ margin: 0, padding: "0 100px 0 16px" }}
        style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
        items={tabs.map((tab) => ({
          key: tab.key,
          label: tab.label,
          children:
            tab.key === activeTab ? (
              <div style={{ padding: 16, overflow: "auto", flex: 1 }}>{children}</div>
            ) : null,
        }))}
      />
      {controls}
    </div>
  );
}

/**
 * Боковое окно (docs/architecture/platform-frontend.md §4, зона 5):
 * По умолчанию 'overlay' (slide-over без Layout Shift).
 * Опционально 'docked' на экранах ≥ 1280px (в сетке).
 * Ширина: default (440px) vs wide (600px).
 */
export function ContextPanel({
  open,
  panelMode = "overlay",
  panelWidth = "default",
  canDock = false,
  ...props
}: ContextPanelProps & { open: boolean }) {
  const widthPx = panelWidth === "wide" ? 600 : 440;
  const isDocked = panelMode === "docked" && canDock;

  if (isDocked) {
    return (
      <Layout.Sider
        id={props.id}
        aria-label={open ? props.label : undefined}
        aria-hidden={!open}
        width={widthPx}
        collapsedWidth={0}
        collapsed={!open}
        trigger={null}
        theme="light"
        style={{
          borderLeft: open ? "1px solid #f0f0f0" : "none",
          overflow: "auto",
          transition: "width 0.2s ease",
        }}
      >
        {open ? (
          <PanelBody {...props} panelMode={panelMode} panelWidth={panelWidth} canDock={canDock} />
        ) : null}
      </Layout.Sider>
    );
  }

  return (
    <Drawer
      open={open}
      onClose={props.onHide}
      mask={false}
      closable={false}
      keyboard
      width={widthPx}
      placement="right"
      rootStyle={{
        top: 56,
        height: "calc(100vh - 56px)",
        pointerEvents: "none",
      }}
      styles={{
        body: { padding: 0 },
        wrapper: {
          maxWidth: "100vw",
          boxShadow: "-4px 0 16px rgba(0, 0, 0, 0.08)",
          borderLeft: "1px solid #f0f0f0",
          transition: "width 0.2s ease",
          pointerEvents: "auto",
        },
      }}
      aria-label={props.label}
      id={props.id}
    >
      <PanelBody {...props} panelMode={panelMode} panelWidth={panelWidth} canDock={canDock} />
    </Drawer>
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
  const widthPx = props.panelWidth === "wide" ? 600 : 440;
  return (
    <Drawer
      open={open}
      onClose={onClose}
      mask={false}
      closable={false}
      keyboard
      width={widthPx}
      placement="right"
      rootStyle={{ top: offsetTop, bottom: offsetBottom, height: "auto", pointerEvents: "none" }}
      styles={{
        body: { padding: 0 },
        wrapper: {
          maxWidth: "100vw",
          boxShadow: "none",
          borderLeft: "1px solid #f0f0f0",
          pointerEvents: "auto",
        },
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
