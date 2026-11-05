import { useTranslation } from "react-i18next";

import type { SigningAuthorityStatus } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";

/** Слово состояния полномочия; цвет — из `STATUS_TONE.signingAuthority` (UX-2b). */
export function AuthorityStatus({ status }: { status: SigningAuthorityStatus }) {
  const { t } = useTranslation("signing");
  return (
    <StatusTag kind="signingAuthority" status={status}>
      {t(`status.${status}`)}
    </StatusTag>
  );
}
