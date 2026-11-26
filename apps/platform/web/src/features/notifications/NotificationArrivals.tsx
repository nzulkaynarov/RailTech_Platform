import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { objectLink } from "../../modules/objectLinks";
import type { Notification } from "../../shared/api/generated/model";
import { showBrowserNotification } from "../../shared/notify/browserNotify";
import { useNotify } from "../../shared/notify/NotifyProvider";
import { readSeen, useNotifyPrefs, writeSeen } from "../../shared/notify/prefs";
import { objectKey } from "./groupNotifications";
import { useNotifications, useReadNotifications } from "./useNotifications";

/** Сколько всплывающих окон сразу; остальные сворачиваются в «Ещё N новых». */
export const MAX_TOASTS = 3;
/** Информационное закрывается само через столько секунд; «требует действия» — только по закрытию. */
export const INFO_SECONDS = 8;
const MORE_KEY = "notify-more";

const at = (item: Notification) => Date.parse(item.created_at);

/**
 * Всплывающие уведомления о новом (УВЕД-1): следит за тем же списком, что и колокольчик (поток подсказок перезапрашивает
 * его), и показывает через единый слой `useNotify` то, что пришло после последнего показанного. Показанное не повторяется
 * после перезагрузки (`readSeen`). Вид «требует действия / к сведению» — поле `needs_action` записи, не код события.
 */
export function NotificationArrivals({
  personId,
  centerOpen,
  onOpenCenter,
}: {
  personId: string;
  /** Колокольчик открыт: окна в углу не нужны, они закрыты и закрывали бы шторку */
  centerOpen: boolean;
  onOpenCenter: () => void;
}) {
  const { t } = useTranslation("shell");
  const notify = useNotify();
  const navigate = useNavigate();
  const { query } = useNotifications();
  const read = useReadNotifications();
  const [prefs] = useNotifyPrefs(personId);
  const items = query.data?.items;
  const itemsRef = useRef<readonly Notification[]>([]);
  const open = useRef(new Set<string>());

  useEffect(() => {
    if (!centerOpen) return;
    for (const key of [...open.current, MORE_KEY]) notify.close(key);
    open.current.clear();
  }, [centerOpen, notify]);

  useEffect(() => {
    if (!items) return;
    itemsRef.current = items;
    // прочитанное в колокольчике или на другом устройстве закрывает своё окно
    for (const key of [...open.current]) {
      if (items.find((n) => n.id === key)?.read) {
        notify.close(key);
        open.current.delete(key);
      }
    }
    const newest = items.reduce((max, n) => Math.max(max, at(n)), 0);
    const seen = readSeen(personId);
    if (seen === null) {
      // первый вход на этом устройстве: накопленное не всплывает
      writeSeen(personId, newest || Date.now());
      return;
    }
    if (newest <= seen) return;
    writeSeen(personId, newest);

    const fresh = items
      .filter((n) => !n.read && at(n) > seen)
      .filter((n) => !prefs.onlyAction || n.needs_action === true)
      .sort((a, b) => at(a) - at(b));
    if (fresh.length === 0) return;

    const openObject = (item: Notification) => {
      const same = itemsRef.current.filter((n) => objectKey(n) === objectKey(item));
      read.markObjectRead(same.length > 0 ? same : [item]);
      if (item.object) void navigate(objectLink(item.object));
    };

    if (prefs.browser) {
      for (const item of fresh) {
        showBrowserNotification({
          tag: item.id,
          title: item.title,
          body: item.subtitle,
          onClick: () => {
            openObject(item);
          },
        });
      }
    }
    if (!prefs.popups) return;

    const single = fresh.length > MAX_TOASTS ? fresh.slice(-(MAX_TOASTS - 1)) : fresh;
    const rest = fresh.length - single.length;
    if (rest > 0) {
      notify.push({
        key: MORE_KEY,
        title: t("notifications.toast.more", { count: rest }),
        duration: fresh.some((n) => n.needs_action === true) ? 0 : INFO_SECONDS,
        action: { label: t("notifications.toast.moreAction"), onClick: onOpenCenter },
      });
    }
    for (const item of single) {
      open.current.add(item.id);
      notify.push({
        key: item.id,
        title: item.title,
        text: item.subtitle,
        duration: item.needs_action === true ? 0 : INFO_SECONDS,
        action: item.object
          ? {
              label: t("notifications.toast.open"),
              onClick: () => {
                openObject(item);
              },
            }
          : {
              label: t("notifications.toast.read"),
              onClick: () => {
                read.markObjectRead([item]);
              },
            },
        onClose: () => {
          open.current.delete(item.id);
        },
      });
    }
  }, [items, personId, prefs, notify, navigate, read, t, onOpenCenter]);

  return null;
}
