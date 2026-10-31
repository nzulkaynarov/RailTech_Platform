import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { StatusTag } from "../../../shared/ui/StatusTag";

/**
 * Статусы документов проекта словами SPEC-v3 §2.4 (слова — `projects:status.*`), цвет — общая карта `STATUS_TONE`
 * (`shared/lib/statuses`, UX-2b). Слова договора, счёта и акта здесь — полный набор D2-5 (в `dictionary` для них прежняя,
 * более короткая карта); неизвестное слово (BFF опередил фронт) показывается как есть нейтральным тегом.
 */
type Kind = "contract" | "invoice" | "act";

export function ProjectStatusTag({
  kind,
  status,
  children,
}: {
  kind: Kind;
  status: string;
  /** Своё слово вместо словарного («Проект · у клиента») */
  children?: ReactNode;
}) {
  const { t } = useTranslation("projects");
  return (
    <StatusTag kind={kind} status={status}>
      {children ?? t(`status.${kind}.${status}`, { defaultValue: status })}
    </StatusTag>
  );
}

export function QuoteAcceptedTag() {
  const { t } = useTranslation("projects");
  return (
    <StatusTag kind="quote" status="accepted">
      {t("status.quote.accepted")}
    </StatusTag>
  );
}
