/**
 * «Отложить до»: время выбирается и показывается в поясе Ташкента (CLAUDE.md §11),
 * независимо от пояса браузера. `DatePicker` работает с «наивным» временем, поэтому
 * переводим: момент → настенные часы Ташкента → момент.
 */
import dayjs, { type Dayjs } from "dayjs";

import { tashkent, TIMEZONE } from "../lib/time";

const WALL = "YYYY-MM-DDTHH:mm:ss";
/** Через сколько по умолчанию напомнить и насколько максимум можно отложить (бэкенд: 7 дней). */
export const SNOOZE_DEFAULT_HOURS = 2;
export const SNOOZE_MAX_DAYS = 7;

/** Момент → «настенное» время Ташкента для пикера (в любом поясе браузера). */
export const toTashkentWall = (value: Date | Dayjs): Dayjs =>
  dayjs(tashkent(value).format(WALL), WALL);

/** «Настенное» время Ташкента из пикера → ISO-момент для API. */
export const fromTashkentWall = (wall: Dayjs): string =>
  dayjs.tz(wall.format(WALL), TIMEZONE).toISOString();

/** Значение пикера по умолчанию: через 2 часа по Ташкенту. */
export const defaultSnooze = (now: Date): Dayjs =>
  toTashkentWall(now).add(SNOOZE_DEFAULT_HOURS, "hour");

/** День недоступен: раньше сегодняшнего (по Ташкенту) или позже лимита. */
export function snoozeDayDisabled(day: Dayjs, now: Date): boolean {
  const today = toTashkentWall(now);
  return day.isBefore(today, "day") || day.isAfter(today.add(SNOOZE_MAX_DAYS, "day"), "day");
}
