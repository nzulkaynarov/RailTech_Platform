/** Часовой пояс компании (docs/architecture/platform-frontend.md §8): даты показываем в нём, а не в поясе браузера. */
export const COMPANY_TIME_ZONE = "Asia/Tashkent";

const LOCALES: Record<string, string> = { ru: "ru-RU", uz: "uz-Latn-UZ", en: "en-GB" };

const UZ_MONTHS = [
  "yanvar",
  "fevral",
  "mart",
  "aprel",
  "may",
  "iyun",
  "iyul",
  "avgust",
  "sentabr",
  "oktabr",
  "noyabr",
  "dekabr",
];
// Индекс — день недели по Intl `en-US` (`short`): воскресенье … суббота
const UZ_WEEKDAYS: Record<string, string> = {
  Sun: "yakshanba",
  Mon: "dushanba",
  Tue: "seshanba",
  Wed: "chorshanba",
  Thu: "payshanba",
  Fri: "juma",
  Sat: "shanba",
};

/**
 * «28-oktabr 2026, chorshanba» (узбекский, латиница). В браузерах без данных `uz` Intl печатает «2026 M10 28, Wed»,
 * поэтому названия месяцев и дней — свои, из Intl берутся только числа и день недели в поясе компании.
 */
function uzTodayLabel(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    day: "numeric",
    month: "numeric",
    year: "numeric",
    timeZone: COMPANY_TIME_ZONE,
  }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const month = UZ_MONTHS[Number(get("month")) - 1] ?? "";
  return `${get("day")}-${month} ${get("year")}, ${UZ_WEEKDAYS[get("weekday")] ?? ""}`;
}

/** «четверг, 22 октября 2026» — дата в подзаголовке «Моей очереди». */
export function todayLabel(language: string, now: Date = new Date()): string {
  if (language === "uz") return uzTodayLabel(now);
  return new Intl.DateTimeFormat(LOCALES[language] ?? "ru-RU", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: COMPANY_TIME_ZONE,
  })
    .format(now)
    .replace(/\s*г\.$/, "");
}

/** Сегодня по календарю компании, `YYYY-MM-DD`. */
export function companyDate(now: number = Date.now()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: COMPANY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(now));
}

/** Дней от сегодня (по календарю компании) до даты `YYYY-MM-DD…`; прошедшая — отрицательное число. */
export function daysUntil(date: string, now: number = Date.now()): number {
  const utc = (value: string) => {
    const [y = Number.NaN, m = Number.NaN, d = Number.NaN] = value
      .slice(0, 10)
      .split("-")
      .map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((utc(date) - utc(companyDate(now))) / 86_400_000);
}
