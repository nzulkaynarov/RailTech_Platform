import { useCallback, useState } from "react";

import { useMe } from "../api/queries";
import { t } from "../i18n/ru";
import type { CrmEvent } from "./useEventStream";

/**
 * Звук и системное уведомление браузера, когда пишет лид текущего менеджера (Q-010).
 * Включается в профиле; выбор хранится в localStorage этого браузера (только удобство).
 */
export const PREF_KEY = "crm.browserAlerts";

export function readPref(): boolean {
  try {
    return window.localStorage.getItem(PREF_KEY) === "1";
  } catch {
    return false;
  }
}

export function writePref(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(PREF_KEY, "1");
    else window.localStorage.removeItem(PREF_KEY);
  } catch {
    // приватный режим или запрет хранилища — настройка просто не запомнится
  }
}

export type Alert = { sound: boolean; notify: boolean };
const NONE: Alert = { sound: false, notify: false };

/** Чистое правило: сообщение лида по моему лиду → звук; вкладка скрыта → ещё и уведомление. */
export function alertFor(
  event: CrmEvent,
  myId: number | undefined,
  enabled: boolean,
  hidden: boolean,
  permission: NotificationPermission | "unsupported",
): Alert {
  if (!enabled || myId === undefined) return NONE;
  if (event.type !== "message.created" || event.role !== "lead") return NONE;
  if (event.assigned_user_id !== myId) return NONE;
  return { sound: true, notify: hidden && permission === "granted" };
}

function permissionNow(): NotificationPermission | "unsupported" {
  return typeof Notification === "undefined" ? "unsupported" : Notification.permission;
}

/** Короткий сигнал без файла-ресурса: синус 880 Гц, 0,15 с. */
export function beep(): void {
  try {
    const Ctx = window.AudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.value = 0.1;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.15);
    osc.onended = () => void ctx.close();
  } catch {
    // нет Web Audio или браузер не дал играть без жеста — молча пропускаем
  }
}

function show(event: CrmEvent): void {
  try {
    const body = t.notify.browserBody.replace("{id}", String(event.lead_id ?? ""));
    new Notification(t.notify.browserTitle, { body, tag: `lead-${String(event.lead_id)}` });
  } catch {
    // уведомления недоступны (iOS Safari вне PWA и т. п.)
  }
}

/** Обработчик событий SSE для шапки: решает по `alertFor` и подаёт сигнал. */
export function useLeadAlertHandler(): (event: CrmEvent) => void {
  const { data: me } = useMe();
  const myId = me?.id;
  return useCallback(
    (event: CrmEvent) => {
      const alert = alertFor(event, myId, readPref(), document.hidden, permissionNow());
      if (alert.sound) beep();
      if (alert.notify) show(event);
    },
    [myId],
  );
}

/** Переключатель в профиле: включение просит разрешение браузера (только по клику). */
export function useBrowserAlertsPref(): {
  enabled: boolean;
  denied: boolean;
  toggle: (on: boolean) => Promise<void>;
} {
  const [enabled, setEnabled] = useState(readPref);
  const [denied, setDenied] = useState(() => permissionNow() === "denied");
  const toggle = useCallback(async (on: boolean) => {
    writePref(on);
    setEnabled(on);
    if (!on || typeof Notification === "undefined") return;
    if (Notification.permission === "default") {
      const result = await Notification.requestPermission();
      setDenied(result === "denied");
    }
  }, []);
  return { enabled, denied, toggle };
}
