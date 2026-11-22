import { useTranslation } from "react-i18next";

import type { EdsRegistryKind } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ProjectStatusTag } from "../projects/status";
import { statusEntry } from "./statusEntry";

/** Тег статуса: слово всегда; неизвестный код (EDS опередил фронт) показывается как есть нейтральным тегом. */
export function DocumentStatusTag({ kind, status }: { kind: EdsRegistryKind; status: string }) {
  const { t } = useTranslation(["documents", "dictionary", "projects"]);
  // Договор, счёт и акт проекта: слова SPEC-v3 §2.4 — те же, что в карточке проекта.
  // Реестр не знает, есть ли файл скана: `signed` акта — «Принят» (без «скан»), «скан» — только в карточке проекта.
  if (kind === "act" && status === "signed") {
    return (
      <ProjectStatusTag kind="act" status={status}>
        {t("projects:status.act.accepted")}
      </ProjectStatusTag>
    );
  }
  if (kind === "contract" || kind === "invoice" || kind === "act") {
    return <ProjectStatusTag kind={kind} status={status} />;
  }
  const entry = statusEntry(kind, status);
  return (
    <StatusTag kind={entry.kind} status={status}>
      {entry.key ? t(entry.key) : status}
    </StatusTag>
  );
}
