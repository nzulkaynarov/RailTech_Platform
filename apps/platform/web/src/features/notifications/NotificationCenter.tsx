import { Button, Segmented, Select, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Notification, NotificationTab } from "../../shared/api/generated/model";
import { EmptyState } from "../../shared/ui/EmptyState";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { NotificationList } from "./NotificationList";
import { useNotifications, useReadNotifications } from "./useNotifications";
import "./notifications.css";

/** Куда ведёт «Все уведомления»: вкладка «Уведомления» бокового окна «Моей очереди». Сохранено для совместимости. */
export const ALL_NOTIFICATIONS_PATH = "/dashboard/queue?panel=open&tab=notifications";

export interface NotificationCenterProps {
  /** `drawer` / `popover` — в шторке колокольчика, `panel` — вкладка бокового окна Dashboard (плоский список) */
  variant: "popover" | "panel" | "drawer";
  /** Закрыть окно после перехода по уведомлению */
  onClose?: () => void;
}

/**
 * Центр уведомлений (SPEC-v3 §6.4, UX-Shell v2):
 * В режиме Drawer/Popover — панель управления с Segmented (Непрочитанные (N) / Все) и Select категорий.
 * В режиме панели Dashboard (variant="panel") — плоский список с кнопкой «Отметить все прочитанными».
 * Данные — `GET /notifications`, опрос 30 с и при фокусе.
 */
export function NotificationCenter({ variant, onClose }: NotificationCenterProps) {
  const { t } = useTranslation("shell");
  const { query, enabled } = useNotifications();
  const read = useReadNotifications();
  const [readScope, setReadScope] = useState<"unread" | "all">("unread");
  const [category, setCategory] = useState<NotificationTab>("all");
  // Защита от исчезновения уведомления при раскрытии «Где посмотреть» в режиме «Непрочитанные»
  const [pinnedIds, setPinnedIds] = useState<string[]>([]);

  const page = query.data;
  const items = page?.items ?? [];
  const unread = page?.unread_count ?? items.filter((n) => !n.read).length;

  const shown =
    variant === "panel"
      ? items
      : items.filter((item) => {
          if (readScope === "unread" && item.read && !pinnedIds.includes(item.id)) return false;
          if (category !== "all" && item.tab !== category) return false;
          return true;
        });

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
          setPinnedIds((prev) => (prev.includes(item.id) ? prev : [...prev, item.id]));
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
        onClick={() => {
          read.markAll();
        }}
      >
        {t("notifications.markAll")}
      </Button>
    </div>
  );

  return (
    <div
      className="pf-notes-section"
      style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
    >
      <SourceBanner
        sources={page?.sources}
        onRetry={() => {
          void query.refetch();
        }}
      />
      {variant !== "panel" ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            padding: "8px 16px",
            borderBottom: "1px solid #f0f0f0",
            background: "#fff",
            flex: "0 0 auto",
          }}
        >
          <Segmented<"unread" | "all">
            size="small"
            value={readScope}
            onChange={(val) => {
              setPinnedIds([]);
              setReadScope(val);
            }}
            options={[
              {
                value: "unread",
                label: unread > 0 ? "Непрочитанные (" + String(unread) + ")" : "Непрочитанные",
              },
              {
                value: "all",
                label: "Все",
              },
            ]}
          />
          <Select<NotificationTab>
            size="small"
            style={{ width: 145 }}
            value={category}
            onChange={(val) => {
              setPinnedIds([]);
              setCategory(val);
            }}
            options={[
              { value: "all", label: "Все типы" },
              { value: "decisions", label: t("notifications.tabs.decisions") },
              { value: "clients", label: t("notifications.tabs.clients") },
              { value: "system", label: t("notifications.tabs.system") },
            ]}
          />
        </div>
      ) : null}
      <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>{body}</div>
      {variant === "panel" && enabled && !query.isPending && !query.isError ? footer : null}
    </div>
  );
}
