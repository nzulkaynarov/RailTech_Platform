import i18n from "../i18n";

const LOCALES: Record<string, string> = { ru: "ru-RU", uz: "uz-Latn-UZ", en: "en-GB" };
const UNITS = ["b", "kb", "mb", "gb"] as const;

/**
 * Размер файла словами одной функцией на всю Платформу: «512 Б», «2 КБ», «1,5 МБ». Основание 1024, единицы — словарь
 * `ui:fileSize` (ru, uz, en), число — по языку интерфейса, не больше одного знака после запятой.
 */
export function formatFileSize(bytes: number, language: string = i18n.language): string {
  const lang = language.slice(0, 2);
  const safe = Number.isFinite(bytes) && bytes > 0 ? bytes : 0;
  let value = safe;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const number = new Intl.NumberFormat(LOCALES[lang] ?? "ru-RU", {
    maximumFractionDigits: unit === 0 ? 0 : 1,
  }).format(value);
  return i18n.getFixedT(lang, "ui")(`fileSize.${UNITS[unit] ?? "b"}`, { value: number });
}
