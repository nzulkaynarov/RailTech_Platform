/** Уведомления браузера (Web Notifications): разрешение просим только по щелчку в настройках, не при загрузке. */
export type BrowserPermission = "unsupported" | "default" | "granted" | "denied";

export function browserPermission(): BrowserPermission {
  return typeof Notification === "undefined" ? "unsupported" : Notification.permission;
}

export async function requestBrowserPermission(): Promise<BrowserPermission> {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.requestPermission();
}

/** Показать уведомление браузера, только если вкладка в фоне и разрешение уже дано. */
export function showBrowserNotification(options: {
  tag: string;
  title: string;
  body?: string | undefined;
  onClick: () => void;
}): void {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  if (!document.hidden) return;
  const shown = new Notification(options.title, {
    tag: options.tag,
    ...(options.body ? { body: options.body } : {}),
  });
  shown.onclick = () => {
    window.focus();
    options.onClick();
    shown.close();
  };
}
