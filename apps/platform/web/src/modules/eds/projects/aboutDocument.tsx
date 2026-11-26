import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useFormat } from "../../../shared/lib/useFormat";
import type { DefinitionItem } from "../../../shared/ui/DefinitionList";

/** «О документе» для просмотра: что про файл уже знает карточка проекта — вид, номер, дата, статус, контрагент. */
export function useAboutDocument() {
  const { t } = useTranslation("ui");
  const { date } = useFormat();
  return ({
    kind,
    number,
    on,
    status,
    client,
  }: {
    kind: string;
    number: string;
    on: string | null | undefined;
    status: ReactNode;
    client: string;
  }): DefinitionItem[] => [
    { label: t("documentViewer.fields.kind"), value: kind },
    { label: t("documentViewer.fields.number"), value: number },
    { label: t("documentViewer.fields.date"), value: on ? date(on) : null },
    { label: t("documentViewer.fields.status"), value: status },
    { label: t("documentViewer.fields.client"), value: client },
  ];
}
