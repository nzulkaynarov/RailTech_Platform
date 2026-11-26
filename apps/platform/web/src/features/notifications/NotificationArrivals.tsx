import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { objectLink } from "../../modules/objectLinks";
import type { Notification } from "../../shared/api/generated/model";
import { showBrowserNotification } from "../../shared/notify/browserNotify";
import { useNotify } from "../../shared/notify/NotifyProvider";
import { readSeenIds, useNotifyPrefs, writeSeenIds } from "../../shared/notify/prefs";
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
 * после перезагрузки (`readSeenIds`: по идентификаторам, а не по времени). Вид «требует действия / к сведению» — поле `needs_action` записи, не код события.
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
  const open = useRef(new Map<string, Notification>());

  useEffect(() => {
    if (!centerOpen) return;
    for (const key of [...open.current.keys(), MORE_KEY]) notify.close(key);
    open.current.clear();
  }, [centerOpen, notify]);

  useEffect(() => {
    if (!items) return;
    itemsRef.current = items;
    // прочитанное в колокольчике или на другом устройстве закрывает своё окно
    for (const key of [...open.current.keys()]) {
      if (items.find((n) => n.id === key)?.read) {
        notify.close(key);
        open.current.delete(key);
      }
    }
    const known = readSeenIds(personId);
    if (known === null) {
      // первый вход на этом устройстве: накопленное не всплывает
      writeSeenIds(
        personId,
        items.map((n) => n.id),
      );
      return;
    }
    const knownSet = new Set(known);
    const fresh = items.filter((n) => !knownSet.has(n.id)).sort((a, b) => at(a) - at(b));
    if (fresh.length === 0) return;
    writeSeenIds(personId, [...known, ...fresh.map((n) => n.id)]);
    const shown = fresh
      .filter((n) => !n.read)
      .filter((n) => !prefs.onlyAction || n.needs_action === true);
    if (shown.length === 0) return;

    const openObject = (item: Notification) => {
      const same = itemsRef.current.filter((n) => objectKey(n) === objectKey(item));
      read.markObjectRead(same.length > 0 ? same : [item]);
      if (item.object) void navigate(objectLink(item.object));
    };

    if (prefs.browser) {
      for (const item of shown) {
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

    // окон всего не больше трёх: старые открытые и новые вместе, лишнее — в «Ещё N новых»
    const all = [...open.current.values(), ...shown].sort((x, y) => at(x) - at(y));
    const single = all.length > MAX_TOASTS ? all.slice(-(MAX_TOASTS - 1)) : all;
    const rest = all.length - single.length;
    for (const [key] of [...open.current]) {
      if (!single.some((n) => n.id === key)) {
        notify.close(key);
        open.current.delete(key);
      }
    }
    if (rest > 0) {
      notify.push({
        key: MORE_KEY,
        title: t("notifications.toast.more", { count: rest }),
        duration: all.some((n) => n.needs_action === true) ? 0 : INFO_SECONDS,
        action: { label: t("notifications.toast.moreAction"), onClick: onOpenCenter },
      });
    }
    for (const item of single) {
      if (open.current.has(item.id)) continue;
      open.current.set(item.id, item);
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
