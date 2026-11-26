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
  undelivered = false,
}: {
  kind: EdsRegistryKind;
  status: string;
  awaitingSignature?: boolean;
  /** EDS ставит `sent` при подписи, до доставки: письмо, которое не ушло адресату, — «Не отправлено», а не «Отправлено». */
  undelivered?: boolean;
}) {
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
  if (kind === "letter_out" && status === "sent" && undelivered) {
    return <StatusTag tone="red">{t("documents:panel.mailFailed")}</StatusTag>;
  }
  const entry = statusEntry(kind, status, awaitingSignature);
  return (
    <StatusTag kind={entry.kind} status={entry.code}>
      {entry.key ? t(entry.key) : status}
    </StatusTag>
  );
}
