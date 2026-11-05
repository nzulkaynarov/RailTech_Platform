import { useTranslation } from "react-i18next";

import type { SigningAuthority } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";

/** Основание словами: «Устав», «Доверенность № 17 от 01.03.2026». */
export function useBasisText(): (row: SigningAuthority) => string {
  const { t } = useTranslation("signing");
  const format = useFormat();
  return (row) => {
    const basis = t(`basis.${row.basis}`);
    if (row.basis === "charter" || !row.basis_number || !row.basis_date) return basis;
    return t("basis.numbered", {
      basis,
      number: row.basis_number,
      date: format.date(row.basis_date),
    });
  };
}
