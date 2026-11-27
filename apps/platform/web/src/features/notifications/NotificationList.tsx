import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { objectLink } from "../../modules/objectLinks";
import type { Notification } from "../../shared/api/generated/model";
import { statusStyle } from "../../shared/lib/statuses";
import { groupNotifications, type NotificationGroup } from "./groupNotifications";
import { relativeTime } from "./relativeTime";
import "./notifications.css";

/** Вид объекта словом (по словарю), без букв-сокращений; нет объекта — тип уведомления. Цвет — карта `notification`. */
export function NotificationChip({ item }: { item: Pick<Notification, "tab" | "object"> }) {
  const { t } = useTranslation("shell");
  const text = item.object
    ? t(`notifications.kindName.${item.object.kind}`)
    : t(`notifications.tabName.${item.tab}`);
  return (
    <span className="pf-kind" style={statusStyle("notification", item.tab)} title={text}>
      {text}
    </span>
  );
}

export interface NotificationListProps {
  items: readonly Notification[];
  /** Клик по уведомлению: отметить прочитанными все уведомления его объекта; переход делает сама ссылка */
  onOpen: (item: Notification, sameObject: readonly Notification[]) => void;
  /** Имя списка для скринридера */
  label: string;
}

/**
 * Список уведомлений (SPEC-v3 §6.4): события одного объекта — одна строка со счётчиком и раскрытием, непрочитанные выше и
 * подсвечены, помечены словом «Новое» для скринридера (не только цветом). Уведомление с объектом — ссылка на объект и
 * нужную вкладку бокового окна (`?panel=open&tab=`); без объекта — кнопка «прочитано».
 */
export function NotificationList({ items, onOpen, label }: NotificationListProps) {
  const { t, i18n } = useTranslation("shell");
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const now = new Date();
  const labels = {
    now: t("notifications.now"),
    minutes: (count: number) => t("notifications.minutes", { count }),
    hours: (count: number) => t("notifications.hours", { count }),
  };
  const groups = groupNotifications(items);

  const row = (item: Notification, group: NotificationGroup, head: boolean): ReactNode => {
    const many = head && group.items.length > 1;
    const unread = head ? group.unread > 0 : !item.read;
    const title = many
      ? `${t(`notifications.kindName.${item.object?.kind ?? "request"}`)} ${item.object?.number ?? ""}`
      : item.title;
    const hint = many ? item.title : item.subtitle;
    const body: ReactNode = (
      <>
        {head ? <NotificationChip item={item} /> : null}
        <span className="pf-note-body">
          <span className="pf-note-title" style={{ display: "block" }}>
            {unread ? <span className="pf-sr-only">{t("notifications.unreadMark")}: </span> : null}
            {title}
            {many ? (
              <span className="pf-note-count">
                {" · "}
                {t("notifications.events", { count: group.items.length })}
              </span>
            ) : null}
          </span>
          {hint ? (
            <span className="pf-hint" style={{ display: "block" }}>
              {hint}
            </span>
          ) : null}
        </span>
        <span className="pf-note-time">
          {relativeTime(item.created_at, now, labels, i18n.language)}
        </span>
      </>
    );
    const className = unread ? "pf-note pf-note--unread" : "pf-note";
    const to = item.object ? objectLink(item.object) : undefined;
    const open = () => {
      onOpen(item, group.items);
    };
    return to ? (
      <Link to={to} className={className} onClick={open}>
        {body}
      </Link>
    ) : (
      <button type="button" className={className} onClick={open}>
        {body}
      </button>
    );
  };

  return (
    <ul className="pf-notes" aria-label={label}>
      {groups.map((group) => {
        const many = group.items.length > 1;
        const open = expanded.has(group.key);
        return (
          <li key={group.key}>
            {row(group.head, group, true)}
            {many ? (
              <>
                <button
                  type="button"
                  className="pf-note-toggle"
                  aria-expanded={open}
                  onClick={() => {
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(group.key)) next.delete(group.key);
                      else next.add(group.key);
                      return next;
                    });
                  }}
                >
                  {open ? t("notifications.collapse") : t("notifications.expand")}
                </button>
                {open ? (
                  <ul className="pf-notes pf-notes--nested">
                    {group.items.map((item) => (
                      <li key={item.id}>{row(item, group, false)}</li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
