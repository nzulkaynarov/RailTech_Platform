/** «3 минуты назад» на языке интерфейса: для подписи «проверено …» у статуса. Будущее время не показываем («только что»). */
export function agoText(language: string, value: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(value).getTime()) / 1000));
  const format = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
  if (seconds < 60) return format.format(0, "second");
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return format.format(-minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (hours < 24) return format.format(-hours, "hour");
  return format.format(-Math.round(hours / 24), "day");
}
