import { t } from "../i18n/ru";

type TitleOptions = {
  resource?: { name?: string; meta?: { label?: string } };
  action?: string;
  params?: Record<string, unknown>;
  pathname?: string;
};

/** Страницы вне ресурсов Refine. */
const STATIC_PAGES: Record<string, string> = {
  "/login": t.page["login"] ?? "",
  "/change-password": t.page["changePassword"] ?? "",
  "/setup": t.page["setup"] ?? "",
};

/** Карточки: «Лид #11», «Клиент #4». */
const SHOW_PAGES: Record<string, string> = {
  leads: t.page["lead"] ?? "",
  clients: t.page["client"] ?? "",
};

function sectionTitle({ resource, action, params, pathname }: TitleOptions): string | null {
  if (pathname && pathname in STATIC_PAGES) return STATIC_PAGES[pathname] ?? null;
  const id = params?.id;
  const show = resource?.name ? SHOW_PAGES[resource.name] : undefined;
  if (action === "show" && show && (typeof id === "string" || typeof id === "number")) {
    return show.replace("{id}", String(id));
  }
  const page = resource?.name ? t.page[resource.name] : undefined;
  if (page) return page;
  if (!pathname || pathname === "/") return null;
  return t.page["notFound"] ?? null;
}

/**
 * Заголовок вкладки по маршруту (WCAG 2.4.2): «<Раздел> — RailTech CRM».
 * Обработчик для `DocumentTitleHandler` из `@refinedev/react-router`.
 */
export function documentTitle(options: TitleOptions): string {
  const section = sectionTitle(options);
  return section ? t.app.documentTitle.replace("{page}", section) : t.app.title;
}
