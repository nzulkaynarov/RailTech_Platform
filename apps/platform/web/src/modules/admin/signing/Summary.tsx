import { useTranslation } from "react-i18next";

import type { SigningAuthorityDetail } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { useBasisText } from "./useBasisText";

/** Отозванное полномочие только читается: сводка вместо формы (менять нечего, выдают новое). */
export function Summary({
  authority,
  kindName,
}: {
  authority: SigningAuthorityDetail;
  kindName: (code: string) => string;
}) {
  const { t } = useTranslation("signing");
  const format = useFormat();
  const basisText = useBasisText();
  return (
    <DefinitionList
      items={[
        { label: t("form.holder"), value: authority.holder.name },
        { label: t("form.kinds"), value: authority.kinds.map(kindName).join(", ") },
        { label: t("form.basis"), value: basisText(authority) },
        {
          label: t("col.term"),
          value: authority.valid_to
            ? `${t("term.from", { date: format.date(authority.valid_from) })} ${t("term.until", { date: format.date(authority.valid_to) })}`
            : `${t("term.from", { date: format.date(authority.valid_from) })}, ${t("term.open")}`,
        },
        {
          label: t("form.limit"),
          value: authority.limit ? (
            <MoneyText value={authority.limit.amount} currency={authority.limit.currency} />
          ) : (
            t("limit.none")
          ),
        },
        { label: t("form.vakolat"), value: authority.vakolat_url },
        { label: t("form.note"), value: authority.note },
        { label: t("form.file"), value: authority.file?.name },
      ]}
    />
  );
}
