import { Button, Drawer, Layout, Tooltip, theme } from "antd";
import { type ReactNode, useEffect, useRef } from "react";
import { Link } from "react-router";

import { BellIcon, ExpandRightIcon, HelpIcon, PanelIcon } from "./icons";
import "./shell.css";

export interface Crumb {
  label: string;
  /** Нет `to` у текущего (последнего) элемента */
  to?: string;
}

const MENU_SHORTCUT =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent)
    ? "⌘\\"
    : "Ctrl+\\";

export interface TopBarProps {
  crumbs: readonly Crumb[];
  labels: {
    crumbs: string;
    /** «Меню» — кнопка возврата свёрнутого подменю */
    menu: string;
    /** Полное имя кнопки: «Центр уведомлений» или «Центр уведомлений, N новых» */
    bell: string;
    /** Имя и подсказка иконочной кнопки окна: «Скрыть панель» / «Показать панель» */
    hidePanel: string;
    showPanel: string;
  };
  /** Кнопка «›› Меню» — подменю свёрнуто (desktop) или открывается Drawer (< 768) */
  onShowMenu?: () => void;
  /** Поле глобального поиска с результатами (`GlobalSearch`): ширина и ⌘K — его забота */
  search: ReactNode;
  unread: number;
  bellContent: ReactNode;
  bellTitle: string;
  bellExtra?: ReactNode;
  /** Окно уведомлений открыто — состояние снаружи, чтобы закрыть его после перехода по уведомлению */
  bellOpen: boolean;
  onBellOpenChange: (open: boolean) => void;
  /** Кнопка «?» рядом с колокольчиком (W15-H7): открывает окно помощи; нет — кнопки нет */
  help?: {
    label: string;
    open: boolean;
    onClick: () => void;
    /** Отметка «Новое» (W-REL): есть запись «Что нового», которую сотрудник не открывал; слово — в `label` */
    fresh?: boolean;
  };
  /**
   * Нет бокового окна у раздела (`/me`, `/help`, 403, 404) — кнопка окна невидима (`visibility: hidden`), но место
   * держит: поиск, «?» и колокольчик стоят на одном x во всех разделах (UX-1b, S5).
   */
  hasPanel: boolean;
  panelOpen: boolean;
  onTogglePanel: () => void;
  panelId: string;
  mobile: boolean;
}

function Crumbs({ crumbs, label }: { crumbs: readonly Crumb[]; label: string }) {
  const { token } = theme.useToken();
  return (
    <nav aria-label={label} className="pf-crumbs-nav">
      <ol className="pf-crumbs">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={`${String(index)}-${crumb.label}`}>
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
              {last ? null : (
                <span aria-hidden="true" className="pf-crumbs-sep">
                  /
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * Шапка 56 px: крошки, поиск (слот), «?», колокольчик, кнопка окна (docs/architecture/platform-frontend.md §4, зона 3).
 * Ширина правой группы постоянна: крошки занимают гибкую область и обрезаются многоточием, кнопка окна — иконка 32 px
 * и не исчезает из потока (UX-1b, S5). Так поиск стоит на одном x при переходах и при открытии и закрытии окна.
 */
export function TopBar({
  crumbs,
  labels,
  onShowMenu,
  search,
  unread,
  bellContent,
  bellTitle,
  bellExtra,
  bellOpen,
  onBellOpenChange,
  help,
  hasPanel,
  panelOpen,
  onTogglePanel,
  panelId,
  mobile,
}: TopBarProps) {
  const { token } = theme.useToken();
  const panelLabel = panelOpen ? labels.hidePanel : labels.showPanel;
  const bellRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // Окно уведомлений — диалог в портале в конце body: при открытии фокус переходит внутрь (на выбранную вкладку),
  // Escape закрывает окно и возвращает фокус на колокольчик (клавиатурный путь без мыши). Окно показывается не
  // сразу (портал, переход), поэтому фокус ставится по кадрам, пока элемент не станет доступен.
  useEffect(() => {
    if (!bellOpen) return;
    let frame = 0;
    let tries = 0;
    const focusInside = () => {
      const target = dialogRef.current?.querySelector<HTMLElement>(
        '[role="tab"][aria-selected="true"], .ant-segmented-item-selected input, button:not(:disabled), a',
      );
      target?.focus();
      if (target && document.activeElement === target) return;
      if (tries++ < 60) frame = window.requestAnimationFrame(focusInside);
    };
    frame = window.requestAnimationFrame(focusInside);
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [bellOpen]);
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
          <Button
            onClick={onShowMenu}
            icon={<ExpandRightIcon />}
            title={`${labels.menu} (${MENU_SHORTCUT})`}
            style={{ padding: "0 10px" }}
          >
            {labels.menu}
          </Button>
        )
      ) : null}
      {mobile ? null : <Crumbs crumbs={crumbs} label={labels.crumbs} />}
      {search}
      {help ? (
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={help.label}
          aria-haspopup="dialog"
          aria-expanded={help.open}
          data-tour="help"
          data-fresh={help.fresh ? "true" : undefined}
          onClick={help.onClick}
          style={{ position: "relative", width: 32, height: 32, flex: "0 0 auto" }}
        >
          <HelpIcon />
          {help.fresh ? <span className="pf-help-fresh" aria-hidden="true" /> : null}
        </button>
      ) : null}
      <button
        ref={bellRef}
        type="button"
        className="pf-icon-btn pf-focusable"
        aria-label={labels.bell}
        aria-haspopup="dialog"
        data-tour="bell"
        onClick={() => {
          onBellOpenChange(!bellOpen);
        }}
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
      <Drawer
        open={bellOpen}
        onClose={() => {
          onBellOpenChange(false);
          bellRef.current?.focus();
        }}
        placement="right"
        width={420}
        title={bellTitle}
        extra={bellExtra}
        aria-label={bellTitle}
        styles={{
          wrapper: { maxWidth: "100vw" },
          body: { padding: 0, display: "flex", flexDirection: "column" },
        }}
      >
        <div ref={dialogRef} style={{ height: "100%", display: "flex", flexDirection: "column" }}>
          {bellContent}
        </div>
      </Drawer>
      {/* Подсказка — слева, в строке шапки: снизу она ложилась на кнопку «›» открытого окна. На телефоне её нет. */}
      <Tooltip title={hasPanel && !mobile ? panelLabel : undefined} placement="left">
        <button
          type="button"
          className="pf-icon-btn pf-focusable"
          aria-label={panelLabel}
          aria-expanded={panelOpen}
          aria-controls={hasPanel ? panelId : undefined}
          aria-hidden={hasPanel ? undefined : true}
          disabled={!hasPanel}
          tabIndex={hasPanel ? undefined : -1}
          data-testid="panel-toggle"
          onClick={onTogglePanel}
          style={{
            width: 32,
            height: 32,
            flex: "0 0 auto",
            visibility: hasPanel ? undefined : "hidden",
          }}
        >
          <PanelIcon />
        </button>
      </Tooltip>
    </Layout.Header>
  );
}
