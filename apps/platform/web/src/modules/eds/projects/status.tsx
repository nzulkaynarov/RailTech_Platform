import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  ProjectActRefStatus,
  ProjectContractRefStatus,
  ProjectInvoiceRefStatus,
} from "../../../shared/api/generated/model";
import type { StatusTone } from "../../../shared/lib/statuses";
import { StatusTag } from "../../../shared/ui/StatusTag";

/**
 * Статусы документов проекта словами SPEC-v3 §2.4 (слова — `projects:status.*`) и цветом. Слова договора, счёта и акта здесь
 * — полный набор D2-5 (в `dictionary` для них прежняя, более короткая карта); неизвестное слово (BFF опередил фронт)
 * показывается как есть нейтральным тегом.
 */
const CONTRACT: Record<ProjectContractRefStatus, StatusTone> = {
  project: "default",
  client_agreed: "blue",
  issued_at_operator: "gold",
  signed: "green",
  rejected: "red",
  cancelled: "default",
};

const INVOICE: Record<ProjectInvoiceRefStatus, StatusTone> = {
  to_issue: "default",
  issued: "blue",
  partial: "gold",
  paid: "green",
  overdue: "red",
  cancelled: "default",
};

const ACT: Record<ProjectActRefStatus, StatusTone> = {
  project: "default",
  returned: "gold",
  issued: "blue",
  signed: "green",
  cancelled: "default",
};

type Kind = "contract" | "invoice" | "act";
const TONES: Record<Kind, Record<string, StatusTone>> = {
  contract: CONTRACT,
  invoice: INVOICE,
  act: ACT,
};

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
  const tone = TONES[kind][status];
  return (
    <StatusTag tone={tone ?? "default"}>
      {children ?? (tone ? t(`status.${kind}.${status}`) : status)}
    </StatusTag>
  );
}

export function QuoteAcceptedTag() {
  const { t } = useTranslation("projects");
  return <StatusTag tone="green">{t("status.quote.accepted")}</StatusTag>;
}
