/** Часовой пояс компании (03-frontend.md §8): даты показываем в нём, а не в поясе браузера. */
export const COMPANY_TIME_ZONE = "Asia/Tashkent";

const LOCALES: Record<string, string> = { ru: "ru-RU", uz: "uz-Latn-UZ", en: "en-GB" };

/** «четверг, 22 октября 2026» — дата в подзаголовке «Моей очереди». */
export function todayLabel(language: string, now: Date = new Date()): string {
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
