const LOCALES: Record<string, string> = { ru: "ru-RU", uz: "uz-Latn-UZ", en: "en-GB" };

/** Размер файла для списка вложений: «512 байт», «2 кБ», «1,5 МБ» — единицы по языку интерфейса. */
export function formatFileSize(bytes: number, language: string): string {
  const locale = LOCALES[language] ?? "ru-RU";
  const megabytes = bytes / (1024 * 1024);
  if (megabytes >= 1) {
    return new Intl.NumberFormat(locale, {
      style: "unit",
      unit: "megabyte",
      unitDisplay: "short",
      maximumFractionDigits: 1,
    }).format(megabytes);
  }
  if (bytes < 1024) {
    return new Intl.NumberFormat(locale, {
      style: "unit",
      unit: "byte",
      unitDisplay: "short",
    }).format(bytes);
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: "kilobyte",
    unitDisplay: "short",
    maximumFractionDigits: 1,
  }).format(bytes / 1024);
}

/** Предел вложения — как в EDS и BFF. */
export const MAX_FILE_BYTES = 25 * 1024 * 1024;
