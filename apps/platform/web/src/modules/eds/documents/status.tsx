import { useTranslation } from "react-i18next";

import type { EdsRegistryKind } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { statusEntry } from "./statusEntry";

/** Тег статуса: слово всегда; неизвестный код (EDS опередил фронт) показывается как есть нейтральным тегом. */
export function DocumentStatusTag({ kind, status }: { kind: EdsRegistryKind; status: string }) {
  const { t } = useTranslation(["documents", "dictionary"]);
  const entry = statusEntry(kind, status);
  return <StatusTag tone={entry?.tone ?? "default"}>{entry ? t(entry.key) : status}</StatusTag>;
}
