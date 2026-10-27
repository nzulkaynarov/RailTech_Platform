import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";

import "./journal.css";

export type JournalKind = "people" | "systems";

const HREF: Record<JournalKind, string> = { people: "/admin/audit", systems: "/admin/bus" };

/**
 * Один «Журнал» Настроек (W15-H4, UX-оценка §5 P1-6): фильтр «Действия людей / Обмен между системами» над содержимым.
 * Действия людей — журнал аудита CRM (кто, что и когда изменил); обмен между системами — шина CRM, ERP и EDS. Кому шина
 * не открыта (директор), фильтра нет — только действия людей.
 */
export function JournalFilter({ current }: { current: JournalKind }) {
  const { t } = useTranslation("modules");
  const { me } = useAuth();
  // «Обмен между системами» (шина) читается только при полном доступе к Настройкам (BFF — так же).
  const systems = canSee(me, { resource: "admin", level: "full" });
  if (!systems) return null;
  return (
    <nav className="pf-journal-filter" aria-label={t("admin.journal.filterLabel")}>
      <ul>
        {(["people", "systems"] as const).map((kind) => (
          <li key={kind}>
            <Link
              to={HREF[kind]}
              className="pf-journal-filter-item pf-focusable"
              aria-current={kind === current ? "page" : undefined}
            >
              {t(`admin.journal.${kind}`)}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
