import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectActRef } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { actStateKey } from "./model";

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

/** Тег договора: «Проект» у клиента на согласовании редакции — «На согласовании у клиента» (словарь §3), а не «Черновик». */
export function ContractStatusTag({
  contract,
}: {
  contract: { status: string; sent_to_client?: boolean };
}) {
  const { t } = useTranslation("projects");
  const atClient = contract.status === "project" && contract.sent_to_client === true;
  return (
    <ProjectStatusTag kind="contract" status={contract.status}>
      {atClient ? t("status.contract.at_client") : undefined}
    </ProjectStatusTag>
  );
}

/** Тег акта: цвет — по статусу ERP, слово — по факту скана (`actStateKey`). */
export function ActStatusTag({ act }: { act: Pick<ProjectActRef, "status" | "has_scan"> }) {
  const { t } = useTranslation("projects");
  const key = actStateKey(act);
  return (
    <ProjectStatusTag kind="act" status={act.status}>
      {t(`status.act.${key}`, { defaultValue: act.status })}
    </ProjectStatusTag>
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
