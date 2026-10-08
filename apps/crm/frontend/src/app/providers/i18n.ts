import type { I18nProvider } from "@refinedev/core";

// Строки, которые рисует сам Refine (сайдбар, кнопки, ошибки). Интерфейс команды — русский.
const RU: Record<string, string> = {
  "buttons.logout": "Выйти",
  "pages.error.404": "Страница не найдена",
  "pages.error.backHome": "На главную",
  "notifications.error": "Ошибка",
  "notifications.success": "Готово",
};

export const i18nProvider: I18nProvider = {
  translate: (key: string, _options?: unknown, defaultMessage?: string) =>
    RU[key] ?? defaultMessage ?? key,
  changeLocale: () => Promise.resolve(),
  getLocale: () => "ru",
};
