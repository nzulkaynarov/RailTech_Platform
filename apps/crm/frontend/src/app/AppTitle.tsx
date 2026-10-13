import { Link } from "react-router";

import { t } from "../i18n/ru";

/**
 * Логотип в сайдбаре. Не заголовок: refine `ThemedTitle` рендерит h1, и он конкурировал
 * с заголовком страницы (WCAG 1.3.1, heading-order). h1 — только в `PageHeader`.
 */
export function AppTitle({ collapsed }: { collapsed: boolean }) {
  return (
    <Link to="/" className="app-title" aria-label={t.app.title}>
      <span aria-hidden>{collapsed ? t.app.short : t.app.title}</span>
    </Link>
  );
}
