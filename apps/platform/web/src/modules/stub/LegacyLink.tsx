import { Button } from "antd";
import type { MouseEvent } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useCreateBridgeErpSso } from "../../shared/api/generated/platform-bff";
import type { LegacySystem } from "../bridge";

/**
 * Кнопка «Открыть в старой CRM / старом ERP»: настоящая ссылка в новую вкладку (`target=_blank`, `rel=noopener`).
 * В ERP, если сотруднику выдан доступ, клик сначала просит у BFF одноразовый SSO-адрес (тот же путь, что у кнопки
 * «Перейти в ERP» старой CRM) и открывает его в уже открытой вкладке; не вышло — вкладка получает обычную ссылку, а
 * под кнопкой появляется пояснение. Если браузер закрыл всплывающие окна, срабатывает обычная ссылка.
 */
export function LegacyLink({
  system,
  href,
  sso,
}: {
  system: LegacySystem;
  href: string;
  /** Можно ли впустить в ERP без второго пароля (`Bridge.erp_sso`) */
  sso: boolean;
}) {
  const { t } = useTranslation("bridge");
  const sign = useCreateBridgeErpSso();
  const [failed, setFailed] = useState(false);

  const onClick = (event: MouseEvent<HTMLElement>) => {
    if (system !== "erp" || !sso || sign.isPending) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    const tab = window.open("about:blank", "_blank");
    if (!tab) return;
    event.preventDefault();
    tab.opener = null;
    setFailed(false);
    sign
      .mutateAsync()
      .then((result) => {
        tab.location.replace(result.url);
      })
      .catch(() => {
        setFailed(true);
        tab.location.replace(href);
      });
  };

  return (
    <>
      <Button
        type="primary"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        loading={sign.isPending}
        onClick={onClick}
      >
        {t(`system.${system}.open`)}
        <span className="pf-sr-only"> ({t("newTab")})</span>
      </Button>
      {failed ? (
        <p role="status" style={{ margin: "8px 0 0" }}>
          {t("erpFallback")}
        </p>
      ) : null}
    </>
  );
}
