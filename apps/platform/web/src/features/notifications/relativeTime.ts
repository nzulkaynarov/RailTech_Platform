import { formatActivityTime } from "../../shared/lib/dates";

export interface RelativeLabels {
  now: string;
  minutes: (count: number) => string;
  hours: (count: number) => string;
}

/**
 * Время уведомления в одной строке справа: «сейчас», «5 мин», «1 ч»; старше суток — «вчера 09:24» или дата
 * (часовой пояс компании, docs/architecture/platform-frontend.md §8).
 */
export function relativeTime(
  value: string,
  now: Date,
  labels: RelativeLabels,
  language: string,
): string {
  const then = new Date(value);
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 1) return labels.now;
  if (minutes < 60) return labels.minutes(minutes);
  if (minutes < 24 * 60) return labels.hours(Math.floor(minutes / 60));
  return formatActivityTime(then, { language, now });
}
