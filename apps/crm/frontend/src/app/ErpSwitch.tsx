import { ExportOutlined } from "@ant-design/icons";
import { Button, message } from "antd";
import { useState } from "react";

import { ssoToken } from "../api/generated/crm";
import { ApiError } from "../api/http";
import { canSwitchToErp } from "../domain/platformAccess";
import { errorText, t } from "../i18n/ru";

type Props = {
  /** Профиль из `GET /me`: `sso_enabled` и `platform_access` решают, показывать ли кнопку. */
  identity:
    | { sso_enabled?: boolean | undefined; platform_access?: readonly string[] | undefined }
    | null
    | undefined;
  /** Телефон: короткая подпись. */
  compact: boolean;
};

/**
 * Переход в бэк-офис (ERP) по SSO (CONTRACTS §6). Виден только тому, кому админ выдал доступ к ERP
 * (`platform_access`) при включённом SSO (FIX-03, FIX-11); у остальных кнопки нет в разметке.
 */
export function ErpSwitch({ identity, compact }: Props) {
  const [loading, setLoading] = useState(false);
  if (!canSwitchToErp(identity)) return null;

  const go = async () => {
    setLoading(true);
    try {
      const data = await ssoToken();
      window.location.href = `${data.redirect_url}#token=${data.token}`;
    } catch (err) {
      void message.error(
        errorText(err instanceof ApiError ? err.code : undefined, t.sso.goToErpFailed),
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      icon={<ExportOutlined aria-hidden />}
      loading={loading}
      onClick={() => void go()}
      title={t.sso.goToErpHint}
      aria-label={t.sso.goToErp}
    >
      {compact ? t.sso.goToErpShort : t.sso.goToErp}
    </Button>
  );
}
