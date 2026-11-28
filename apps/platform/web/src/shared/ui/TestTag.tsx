import { useTranslation } from "react-i18next";

import { StatusTag } from "./StatusTag";

/**
 * Метка «Тестовая» (ТЕСТ-2): рядом с названием компании и номером записи, которая принадлежит тестовой компании. Её видно
 * только тем, у кого в профиле включён показ тестовых, — чтобы тестовую запись нельзя было принять за настоящую.
 */
export function TestTag({ value }: { value: boolean | undefined | null }) {
  const { t } = useTranslation("ui");
  if (!value) return null;
  return (
    <StatusTag tone="default" title={t("testTag.hint")}>
      {t("testTag.label")}
    </StatusTag>
  );
}
