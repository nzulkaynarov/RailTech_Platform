import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { BANK_DETAILS_PATH } from "../../../entities/setup/steps";
import { LinkButton } from "../../../shared/ui/LinkButton";

/**
 * «Нет банковских реквизитов компании» (D26G-6): ERP заранее говорит, что «Выставить счёт» откажет
 * (`bank_details_ready = false` — тот же расчёт, что гейт выпуска), и сотрудник узнаёт об этом до клика, а не ошибкой после.
 * Реквизиты вводит администратор в «Настройки · Реквизиты и бланк»; у кого раздел открыт на правку — ссылка туда, у остальных
 * (менеджер-универсал, бухгалтер) — только кому и где, без ссылки в закрытый раздел.
 */
export function BankDetailsNotice() {
  const { t } = useTranslation("payments");
  const { me } = useAuth();
  const canFix = canEdit(me, "company.settings");
  return (
    <Alert
      type="warning"
      showIcon
      role="status"
      message={t("bankDetails.title")}
      description={t("bankDetails.text")}
      action={
        canFix ? (
          <LinkButton size="small" to={BANK_DETAILS_PATH}>
            {t("bankDetails.open")}
          </LinkButton>
        ) : undefined
      }
    />
  );
}
