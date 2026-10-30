import { Button, Segmented, Select, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Notification, NotificationTab } from "../../shared/api/generated/model";
import { EmptyState } from "../../shared/ui/EmptyState";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { NotificationList } from "./NotificationList";
import { useNotifications, useReadNotifications } from "./useNotifications";
import "./notifications.css";

const CATEGORIES: readonly NotificationTab[] = ["decisions", "clients", "system"];

export interface NotificationCenterProps {
  /** `drawer` — шторка колокольчика, `panel` — вкладка бокового окна Dashboard (плоский список) */
  variant: "panel" | "drawer";
  /** Закрыть окно после перехода по уведомлению */
  onClose?: () => void;
}

/**
 * Центр уведомлений (SPEC-v3 §6.4; шторка — ORCHESTRATOR §3 п. 18):
 * в шторке колокольчика — «Непрочитанные (N) / Все» и тип с числом непрочитанных, без ухода с текущего экрана.
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
  const unreadOf = (tab: NotificationTab) => items.filter((n) => n.tab === tab && !n.read).length;

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
            flexWrap: "wrap",
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
                // Ширина сегмента постоянна (UX-1b, S16): невидимый образец «(99)» держит место, цифры — табличные.
                label: (
                  <span className="pf-notes-unread">
                    <span aria-hidden="true" className="pf-notes-unread-ghost">
                      {t("notifications.scope.unreadCount", { count: 99 })}
                    </span>
                    <span>
                      {unread > 0
                        ? t("notifications.scope.unreadCount", { count: unread })
                        : t("notifications.scope.unread")}
                    </span>
                  </span>
                ),
              },
              { value: "all", label: t("notifications.scope.all") },
            ]}
          />
          <Select<NotificationTab>
            size="small"
            aria-label={t("notifications.category")}
            style={{ width: 160 }}
            value={category}
            onChange={(val) => {
              setPinnedIds([]);
              setCategory(val);
            }}
            options={[
              { value: "all", label: t("notifications.allTypes") },
              ...CATEGORIES.map((tab) => {
                const count = unreadOf(tab);
                const name = t(`notifications.tabs.${tab}`);
                return { value: tab, label: count > 0 ? `${name} · ${String(count)}` : name };
              }),
            ]}
          />
        </div>
      ) : null}
      <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>{body}</div>
      {variant === "panel" && enabled && !query.isPending && !query.isError ? footer : null}
    </div>
  );
}
