import { useTranslation } from "react-i18next";

import type { EdsRegistryKind } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ProjectStatusTag } from "../projects/status";
import { statusEntry } from "./statusEntry";

/** Тег статуса: слово всегда; неизвестный код (EDS опередил фронт) показывается как есть нейтральным тегом. */
export function DocumentStatusTag({
  kind,
  status,
  awaitingSignature = false,
}: {
  kind: EdsRegistryKind;
  status: string;
  awaitingSignature?: boolean;
}) {
  const { t } = useTranslation(["documents", "dictionary"]);
  // Договор, счёт и акт проекта: слова SPEC-v3 §2.4 — те же, что в карточке проекта.
  if (kind === "contract" || kind === "invoice" || kind === "act") {
    return <ProjectStatusTag kind={kind} status={status} />;
  }
  const entry = statusEntry(kind, status, awaitingSignature);
  return (
    <StatusTag kind={entry.kind} status={entry.code}>
      {entry.key ? t(entry.key) : status}
    </StatusTag>
  );
}
