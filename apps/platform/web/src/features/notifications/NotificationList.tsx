import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { isActionable } from "../../modules/bridge";
import { objectLink } from "../../modules/objectLinks";
import { WhereToDo } from "../../modules/stub/WhereToDo";
import type { Notification } from "../../shared/api/generated/model";
import { TONE_STYLE, type StatusTone } from "../../shared/lib/statuses";
import { relativeTime } from "./relativeTime";
import "./notifications.css";

/** Цвет значка по вкладке: решения — золотой, клиенты — бирюзовый, система — красный (текст ≥ 4.5:1 на своём фоне). */
const TAB_TONE: Record<Notification["tab"], StatusTone> = {
  all: "blue",
  decisions: "gold",
  clients: "cyan",
  system: "red",
};

export function NotificationChip({ item }: { item: Pick<Notification, "tab" | "object"> }) {
  const { t } = useTranslation("shell");
  const text = item.object
    ? t(`notifications.kindChip.${item.object.kind}`)
    : t(`notifications.tabChip.${item.tab}`);
  return (
    <span className="pf-chip" style={TONE_STYLE[TAB_TONE[item.tab]]} aria-hidden="true">
      {text}
    </span>
  );
}

export interface NotificationListProps {
  items: readonly Notification[];
  /** Клик по уведомлению: отметить прочитанным и закрыть всплывающее окно; переход делает сама ссылка */
  onOpen: (item: Notification) => void;
  /** Только отметить прочитанным, окно не закрывать: уведомление об объекте без экрана раскрывает «Где посмотреть» */
  onRead?: (item: Notification) => void;
  /** Имя списка для скринридера */
  label: string;
}

/**
 * Список уведомлений (SPEC-v3 §6.4): одна строка + подпись, время справа, непрочитанные подсвечены `#f0f7ff` и
 * помечены словом «Новое» для скринридера (не только цветом). Уведомление с объектом — ссылка на объект и нужную
 * вкладку бокового окна (`?panel=open&tab=`); если у раздела объекта ещё нет экрана — кнопка «Где посмотреть»,
 * раскрывающая мост в старый экран (W15-H2); без объекта — кнопка «прочитано».
 */
export function NotificationList({ items, onOpen, onRead, label }: NotificationListProps) {
  const { t, i18n } = useTranslation("shell");
  const [where, setWhere] = useState<string | null>(null);
  const now = new Date();
  const labels = {
    now: t("notifications.now"),
    minutes: (count: number) => t("notifications.minutes", { count }),
    hours: (count: number) => t("notifications.hours", { count }),
  };
  return (
    <ul className="pf-notes" aria-label={label}>
      {items.map((item) => {
        const body: ReactNode = (
          <>
            <NotificationChip item={item} />
            <span className="pf-note-body">
              <span className="pf-note-title" style={{ display: "block" }}>
                {item.read ? null : (
                  <span className="pf-sr-only">{t("notifications.unreadMark")}: </span>
                )}
                {item.title}
              </span>
              {item.subtitle ? (
                <span className="pf-hint" style={{ display: "block" }}>
                  {item.subtitle}
                </span>
              ) : null}
            </span>
            <span className="pf-note-time">
              {relativeTime(item.created_at, now, labels, i18n.language)}
            </span>
          </>
        );
        const className = item.read ? "pf-note" : "pf-note pf-note--unread";
        const to = item.object ? objectLink(item.object) : undefined;
        const stub = to !== undefined && !isActionable(to);
        return (
          <li key={item.id}>
            {to && !stub ? (
              <Link
                to={to}
                className={className}
                onClick={() => {
                  onOpen(item);
                }}
              >
                {body}
              </Link>
            ) : (
              <button
                type="button"
                className={className}
                aria-expanded={stub ? where === item.id : undefined}
                onClick={() => {
                  if (stub) {
                    setWhere(where === item.id ? null : item.id);
                    if (!item.read) onRead?.(item);
                  } else {
                    onOpen(item);
                  }
                }}
              >
                {stub ? <span className="pf-sr-only">{t("notifications.where")}: </span> : null}
                {body}
              </button>
            )}
            {stub && to && where === item.id ? (
              <section className="pf-note-where" aria-label={t("notifications.where")}>
                <WhereToDo path={to} />
              </section>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
