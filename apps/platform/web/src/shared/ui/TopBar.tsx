import { Button, Layout, Popover, theme } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { BellIcon, ExpandRightIcon, PanelIcon } from "./icons";
import "./shell.css";

export interface Crumb {
  label: string;
  /** Нет `to` у текущего (последнего) элемента */
  to?: string;
}

export interface TopBarProps {
  crumbs: readonly Crumb[];
  labels: {
    crumbs: string;
    /** «Меню» — кнопка возврата свёрнутого подменю */
    menu: string;
    /** Полное имя кнопки: «Центр уведомлений» или «Центр уведомлений, N новых» */
    bell: string;
    hidePanel: string;
    showPanel: string;
    /** Имена иконочной кнопки на узком экране (подписи «Панель» там нет) */
    hidePanelIcon: string;
    showPanelIcon: string;
  };
  /** Кнопка «›› Меню» — подменю свёрнуто (desktop) или открывается Drawer (< 768) */
  onShowMenu?: () => void;
  /** Поле глобального поиска с результатами (`GlobalSearch`): ширина и ⌘K — его забота */
  search: ReactNode;
  unread: number;
  bellContent: ReactNode;
  bellTitle: string;
  /** Окно уведомлений открыто — состояние снаружи, чтобы закрыть его после перехода по уведомлению */
  bellOpen: boolean;
  onBellOpenChange: (open: boolean) => void;
  /** Нет бокового окна у раздела (403, 404) — кнопка «Панель» не показывается */
  hasPanel: boolean;
  panelOpen: boolean;
  onTogglePanel: () => void;
  panelId: string;
  mobile: boolean;
}

function Crumbs({ crumbs, label }: { crumbs: readonly Crumb[]; label: string }) {
  const { token } = theme.useToken();
  return (
    <nav aria-label={label}>
      <ol className="pf-crumbs">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={`${String(index)}-${crumb.label}`} style={{ display: "contents" }}>
              {crumb.to && !last ? (
                <Link to={crumb.to} className="pf-focusable">
                  {crumb.label}
                </Link>
              ) : (
                <span
                  aria-current={last ? "page" : undefined}
                  style={{ color: last ? token.colorText : undefined }}
                >
                  {crumb.label}
                </span>
              )}
              {last ? null : <span aria-hidden="true">/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Шапка 56 px: крошки, поиск (слот), колокольчик, «Скрыть панель / Панель» (03-frontend.md §4, зона 3). */
export function TopBar({
  crumbs,
  labels,
  onShowMenu,
  search,
  unread,
  bellContent,
  bellTitle,
  bellOpen,
  onBellOpenChange,
  hasPanel,
  panelOpen,
  onTogglePanel,
  panelId,
  mobile,
}: TopBarProps) {
  const { token } = theme.useToken();
  return (
    <Layout.Header
      style={{
        display: "flex",
        alignItems: "center",
        gap: mobile ? 8 : 12,
        height: 56,
        lineHeight: "normal",
        padding: mobile ? "0 12px" : "0 24px",
        borderBottom: `1px solid ${token.colorSplit}`,
        flex: "0 0 auto",
      }}
    >
      {onShowMenu ? (
        mobile ? (
          <button
            type="button"
            className="pf-icon-btn pf-focusable"
            aria-label={labels.menu}
            onClick={onShowMenu}
            style={{ width: 32, height: 32, flex: "0 0 auto" }}
          >
            <ExpandRightIcon />
          </button>
        ) : (
          <Button onClick={onShowMenu} icon={<ExpandRightIcon />} style={{ padding: "0 10px" }}>
            {labels.menu}
          </Button>
        )
      ) : null}
      {mobile ? null : <Crumbs crumbs={crumbs} label={labels.crumbs} />}
      {mobile ? null : <div style={{ flex: 1 }} />}
      {search}
      <Popover
        trigger="click"
        placement="bottomRight"
        title={bellTitle}
        content={bellContent}
        open={bellOpen}
        onOpenChange={onBellOpenChange}
        styles={{ body: { width: 400, maxWidth: "calc(100vw - 32px)" } }}
      >
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={labels.bell}
          aria-haspopup="dialog"
          style={{ position: "relative", width: 32, height: 32, flex: "0 0 auto" }}
        >
          <BellIcon />
          {unread > 0 ? (
            <span
              className="pf-badge"
              aria-hidden="true"
              style={{
                position: "absolute",
                top: 2,
                right: 0,
                height: 16,
                minWidth: 16,
                lineHeight: "16px",
                fontSize: 10,
                padding: "0 4px",
                marginLeft: 0,
              }}
            >
              {unread}
            </span>
          ) : null}
        </button>
      </Popover>
      {!hasPanel ? null : mobile ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={panelOpen ? labels.hidePanelIcon : labels.showPanelIcon}
          aria-expanded={panelOpen}
          aria-controls={panelId}
          onClick={onTogglePanel}
          style={{ width: 32, height: 32, flex: "0 0 auto" }}
        >
          <PanelIcon />
        </button>
      ) : (
        <Button
          onClick={onTogglePanel}
          aria-expanded={panelOpen}
          aria-controls={panelId}
          icon={<PanelIcon />}
          iconPosition="end"
          style={{ padding: "0 10px" }}
        >
          {panelOpen ? labels.hidePanel : labels.showPanel}
        </Button>
      )}
    </Layout.Header>
  );
}
