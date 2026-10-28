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
