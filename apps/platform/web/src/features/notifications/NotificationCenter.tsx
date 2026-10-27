import { Button, Skeleton, Tabs } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Notification, NotificationTab } from "../../shared/api/generated/model";
import { EmptyState } from "../../shared/ui/EmptyState";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { NotificationList } from "./NotificationList";
import { useNotifications, useReadNotifications } from "./useNotifications";
import "./notifications.css";

const TABS: readonly NotificationTab[] = ["all", "decisions", "clients", "system"];
/** Куда ведёт «Все уведомления»: вкладка «Уведомления» бокового окна «Моей очереди». */
export const ALL_NOTIFICATIONS_PATH = "/dashboard/queue?panel=open&tab=notifications";

export interface NotificationCenterProps {
  /** `popover` — под колокольчиком (вкладки, футер), `panel` — вкладка бокового окна Dashboard (плоский список) */
  variant: "popover" | "panel";
  /** Закрыть окно после перехода по уведомлению */
  onClose?: () => void;
}

function unreadBy(items: readonly Notification[], tab: NotificationTab, total: number): number {
  return tab === "all" ? total : items.filter((n) => n.tab === tab && !n.read).length;
}

/**
 * Центр уведомлений (SPEC-v3 §6.4): вкладки «Все · Решения · Клиенты · Система» с числом непрочитанных, список,
 * «Отметить все прочитанными», «Все уведомления». Данные — `GET /notifications`, опрос 30 с и при фокусе.
 */
export function NotificationCenter({ variant, onClose }: NotificationCenterProps) {
  const { t } = useTranslation("shell");
  const { query, enabled } = useNotifications();
  const read = useReadNotifications();
  const [tab, setTab] = useState<NotificationTab>("all");

  const page = query.data;
  const items = page?.items ?? [];
  const shown = variant === "panel" || tab === "all" ? items : items.filter((n) => n.tab === tab);
  const unread = page?.unread_count ?? 0;

  const open = (item: Notification) => {
    if (!item.read) read.markRead(item.id);
    onClose?.();
  };

  let body;
  if (!enabled) {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("notifications.empty")}
        text={t("notifications.text")}
      />
    );
  } else if (query.isPending) {
    body = (
      <div style={{ padding: 16 }} role="status" aria-label={t("notifications.loading")}>
        <Skeleton active paragraph={{ rows: 3 }} title={false} />
      </div>
    );
  } else if (query.isError) {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("notifications.loadErrorTitle")}
        text={t("notifications.loadErrorText")}
        action={
          <Button
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("notifications.retry")}
          </Button>
        }
      />
    );
  } else if (shown.length === 0) {
    body = (
      <EmptyState
        level={3}
        compact
        title={items.length === 0 ? t("notifications.empty") : t("notifications.emptyTab")}
        text={t("notifications.text")}
      />
    );
  } else {
    body = (
      <NotificationList
        items={shown}
        onOpen={open}
        onRead={(item) => {
          read.markRead(item.id);
        }}
        label={t("notifications.label")}
      />
    );
  }

  const footer = (
    <div className="pf-notes-foot">
      <Button
        type="text"
        size="small"
        disabled={unread === 0 || read.markAllPending}
        onClick={read.markAll}
      >
        {t("notifications.markAll")}
      </Button>
      {variant === "popover" ? (
        <Link to={ALL_NOTIFICATIONS_PATH} onClick={onClose} style={{ fontSize: 12 }}>
          {t("notifications.seeAll")}
        </Link>
      ) : null}
    </div>
  );

  return (
    <div className="pf-notes-section">
      <SourceBanner
        sources={page?.sources}
        onRetry={() => {
          void query.refetch();
        }}
      />
      {variant === "popover" ? (
        <Tabs
          size="small"
          activeKey={tab}
          onChange={(key) => {
            setTab(key as NotificationTab);
          }}
          tabBarStyle={{ margin: 0, padding: "0 16px" }}
          items={TABS.map((key) => {
            const count = unreadBy(items, key, unread);
            return {
              key,
              label: (
                <span>
                  {t(`notifications.tabs.${key}`)}
                  {count > 0 ? (
                    <>
                      {" "}
                      <span className="pf-hint">{count}</span>
                    </>
                  ) : null}
                </span>
              ),
              children: key === tab ? body : null,
            };
          })}
        />
      ) : (
        body
      )}
      {!enabled || query.isPending || query.isError ? null : footer}
    </div>
  );
}
