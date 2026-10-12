/**
 * Время в интерфейсе — всегда Asia/Tashkent (CLAUDE.md §11), независимо от часового
 * пояса браузера; формат с годом, где без него неоднозначно (аудит UI U-08).
 */
import dayjs, { type Dayjs } from "dayjs";
import "dayjs/locale/ru";
import relativeTime from "dayjs/plugin/relativeTime";
import timezone from "dayjs/plugin/timezone";
import utc from "dayjs/plugin/utc";

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(relativeTime);
dayjs.locale("ru");

export const TIMEZONE = "Asia/Tashkent";
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

type Input = string | Date | Dayjs;

/** Момент времени в Ташкенте; дата без времени («2026-07-14») не сдвигается. */
export function tashkent(value: Input): Dayjs {
  if (typeof value === "string" && DATE_ONLY.test(value)) return dayjs(value);
  return dayjs(value).tz(TIMEZONE);
}

/** Форматы дат — для `format(...)` и `DatePicker format=...` (единые на всех экранах). */
export const DATE_FORMAT = "DD.MM.YYYY";
export const DATETIME_FORMAT = "DD.MM.YYYY HH:mm";

export const formatDate = (value: Input): string => tashkent(value).format(DATE_FORMAT);

export const formatDateTime = (value: Input): string => tashkent(value).format(DATETIME_FORMAT);

/** Компактно для лент: сегодня — только время, в этом году — без года, иначе полностью. */
export function formatWhen(value: Input, now: Input = new Date()): string {
  const at = tashkent(value);
  const today = tashkent(now);
  if (at.isSame(today, "day")) return at.format("HH:mm");
  if (at.isSame(today, "year")) return at.format("DD.MM HH:mm");
  return at.format(DATETIME_FORMAT);
}

export const fromNow = (value: Input, now: Input = new Date()): string =>
  tashkent(value).from(tashkent(now));
