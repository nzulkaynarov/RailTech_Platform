import {
  ArrowsAltOutlined,
  PushpinFilled,
  PushpinOutlined,
  ShrinkOutlined,
} from "@ant-design/icons";
import { Drawer, Tabs } from "antd";
import type { KeyboardEvent, ReactNode } from "react";

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
  /** Подписи кнопок ширины и закрепления (i18n `shell:panel.*`) */
  controlLabels?: PanelControlLabels;
}

export interface PanelControlLabels {
  wide: string;
  narrow: string;
  dock: string;
  undock: string;
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
  controlLabels,
}: ContextPanelProps & { withHide?: boolean }) {
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
      {onWidthChange && controlLabels ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={panelWidth === "wide" ? controlLabels.narrow : controlLabels.wide}
          title={panelWidth === "wide" ? controlLabels.narrow : controlLabels.wide}
          onClick={() => {
            onWidthChange(panelWidth === "wide" ? "default" : "wide");
          }}
          style={{ width: 28, height: 28 }}
        >
          {panelWidth === "wide" ? <ShrinkOutlined /> : <ArrowsAltOutlined />}
        </button>
      ) : null}
      {canDock && onModeChange && controlLabels ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={panelMode === "docked" ? controlLabels.undock : controlLabels.dock}
          aria-pressed={panelMode === "docked"}
          title={panelMode === "docked" ? controlLabels.undock : controlLabels.dock}
          onClick={() => {
            onModeChange(panelMode === "docked" ? "overlay" : "docked");
          }}
          style={{ width: 28, height: 28 }}
        >
          {panelMode === "docked" ? (
            <PushpinFilled style={{ color: "var(--ant-color-primary, #1668dc)" }} />
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
              // Полоса прокрутки не меняет ширину тела окна (UX-1b, S15)
              <div style={{ padding: 16, overflow: "auto", flex: 1, scrollbarGutter: "stable" }}>
                {children}
              </div>
            ) : null,
        }))}
      />
      {controls}
    </div>
  );
}

/** Esc внутри бокового окна закрывает его, если клавишу не забрал вложенный список, меню или поле. */
function hideOnEscape(onHide: () => void) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    const target = event.target;
    if (target instanceof HTMLElement && target.closest('[aria-expanded="true"]')) return;
    onHide();
  };
}

/**
 * Боковое окно (docs/architecture/platform-frontend.md §4, зона 5, §4.1; ORCHESTRATOR §3 п. 18).
 * По умолчанию — поверх основного окна у правого края (overlay): таблицы и карточки не сжимаются. Это немодальная
 * область `complementary`, а не Drawer: у Drawer `aria-modal` и ловушка фокуса, а окно не модальное — Tab уходит обратно
 * в таблицу. Рядом (docked) — только когда пользователь закрепил окно булавкой и оно помещается (`docked` решает каркас:
 * ≥ 1280 px и рабочей области ≥ 760 px). Ширина 440 или 600 px — выбор пользователя.
 *
 * «Рядом» и «поверх» — одна обёртка, меняется только класс (UX-1a): булавка и переход порога ширины не размонтируют
 * вкладки и формы окна. Закрытое окно остаётся в документе скрытым (`hidden`) — цель `aria-controls` кнопки «Панель».
 */
export function ContextPanel({
  open,
  docked = false,
  panelMode = "overlay",
  panelWidth = "default",
  canDock = true,
  ...props
}: ContextPanelProps & {
  open: boolean;
  /** Окно сейчас в сетке рядом с основным: закреплено булавкой и помещается (решает каркас) */
  docked?: boolean;
}) {
  const widthPx = panelWidth === "wide" ? 600 : 440;
  return (
    <aside
      id={props.id}
      aria-label={props.label}
      hidden={!open}
      className={docked ? "pf-panel-frame pf-panel-docked" : "pf-panel-frame pf-panel-overlay"}
      style={{ width: docked ? widthPx : `min(${String(widthPx)}px, 100vw)` }}
      onKeyDown={hideOnEscape(props.onHide)}
    >
      {open ? (
        <PanelBody {...props} panelMode={panelMode} panelWidth={panelWidth} canDock={canDock} />
      ) : null}
    </aside>
  );
}

/** < 768 px: боковое окно — `Drawer` без затемнения поверх основного (между шапкой и нижней панелью). */
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
      width={440}
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
