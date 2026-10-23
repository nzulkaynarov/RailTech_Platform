import { COMPANY_TIME_ZONE } from "./format";

/**
 * Даты в часовом поясе компании (docs/architecture/platform-frontend.md §8), а не браузера: сотрудник в другом поясе видит те же «сегодня» и
 * «вчера», что и бухгалтерия. Формат русский `24.10.2026` для ru и uz, `24/10/2026` не используется нигде.
 */
export type DateInput = Date | string | number | null | undefined;

export type DateStyle =
  /** 24.10.2026 */
  | "date"
  /** 24.10 */
  | "short"
  /** 11:50 */
  | "time"
  /** 24.10.2026 11:50 */
  | "datetime"
  /** 24 октября 2026 */
  | "long";

const LOCALES: Record<string, string> = { ru: "ru-RU", uz: "uz-Latn-UZ", en: "en-GB" };
const EM_DASH = "—";
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

interface Parts {
  year: string;
  month: string;
  day: string;
  hour: string;
  minute: string;
}

const partsFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: COMPANY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function partsOf(date: Date): Parts {
  const parts: Record<string, string> = {};
  for (const part of partsFormatter.formatToParts(date)) parts[part.type] = part.value;
  return {
    year: parts["year"] ?? "",
    month: parts["month"] ?? "",
    day: parts["day"] ?? "",
    hour: parts["hour"] ?? "",
    minute: parts["minute"] ?? "",
  };
}

/** Ключ календарного дня компании `2026-10-24` — для сравнения «сегодня» и «вчера». */
export function companyDayKey(value: DateInput): string | null {
  const date = toDate(value);
  if (!date) return null;
  const { year, month, day } = partsOf(date);
  return `${year}-${month}-${day}`;
}

export interface DateFormatOptions {
  language?: string;
  style?: DateStyle;
}

/** Дата или время по стилю; «2026-10-24» без времени показывается как есть, без сдвига поясов. */
export function formatDate(value: DateInput, options: DateFormatOptions = {}): string {
  const { language = "ru", style = "date" } = options;
  const dateOnly = typeof value === "string" ? DATE_ONLY.exec(value) : null;
  if (dateOnly) {
    const [, year = "", month = "", day = ""] = dateOnly;
    if (style === "time") return EM_DASH;
    if (style === "short") return `${day}.${month}`;
    if (style === "long") {
      return longDate(
        new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))),
        language,
        "UTC",
      );
    }
    return `${day}.${month}.${year}`;
  }
  const date = toDate(value);
  if (!date) return EM_DASH;
  if (style === "long") return longDate(date, language, COMPANY_TIME_ZONE);
  const { year, month, day, hour, minute } = partsOf(date);
  switch (style) {
    case "short":
      return `${day}.${month}`;
    case "time":
      return `${hour}:${minute}`;
    case "datetime":
      return `${day}.${month}.${year} ${hour}:${minute}`;
    default:
      return `${day}.${month}.${year}`;
  }
}

function longDate(date: Date, language: string, timeZone: string): string {
  const locale = LOCALES[language.slice(0, 2)] ?? "ru-RU";
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone,
  })
    .format(date)
    .replace(/\s*г\.$/, "");
}

const YESTERDAY: Record<string, string> = { ru: "вчера", uz: "kecha", en: "yesterday" };

/**
 * Время события в ленте и уведомлениях: сегодня — `10:12`, вчера — `вчера 09:24`, раньше — `24.10 11:50`, в прошлом
 * году — с годом.
 */
export function formatActivityTime(
  value: DateInput,
  options: { language?: string; now?: Date } = {},
): string {
  const { language = "ru", now = new Date() } = options;
  const date = toDate(value);
  if (!date) return EM_DASH;
  const day = companyDayKey(date);
  const today = companyDayKey(now);
  const yesterday = companyDayKey(new Date(now.getTime() - 24 * 60 * 60 * 1000));
  const time = formatDate(date, { style: "time" });
  if (day === today) return time;
  if (day === yesterday)
    return `${YESTERDAY[language.slice(0, 2)] ?? YESTERDAY["ru"] ?? ""} ${time}`;
  const sameYear = day?.slice(0, 4) === today?.slice(0, 4);
  return sameYear
    ? `${formatDate(date, { style: "short" })} ${time}`
    : formatDate(date, { style: "datetime" });
}
