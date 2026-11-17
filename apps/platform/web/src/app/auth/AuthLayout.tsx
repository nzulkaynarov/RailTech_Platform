import { Card, theme } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { OperatorMark } from "../../shared/ui/OperatorMark";

/**
 * Рамка экранов вне каркаса (вход, смена пароля): карточка 400 px по центру на фоне `#f5f5f5`, марка оператора (ДВ-3)
 * и строка против фишинга под карточкой.
 */
export function AuthLayout({
  title,
  lead,
  children,
}: {
  title: string;
  lead?: string;
  children: ReactNode;
}) {
  const { token } = theme.useToken();
  const { t } = useTranslation("shell");
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: 16,
        background: token.colorBgLayout,
      }}
    >
      <Card style={{ width: "100%", maxWidth: 400 }} styles={{ body: { padding: 24 } }}>
        <div style={{ marginBottom: 16 }}>
          <OperatorMark />
        </div>
        <h1 style={{ margin: 0, fontSize: 20, lineHeight: "28px", fontWeight: 600 }}>{title}</h1>
        {lead ? <p style={{ margin: "4px 0 0", color: token.colorTextSecondary }}>{lead}</p> : null}
        <div style={{ marginTop: 24 }}>{children}</div>
        <p style={{ margin: "24px 0 0", fontSize: 12, color: token.colorTextSecondary }}>
          {t("login.antiPhishing")}
        </p>
      </Card>
    </main>
  );
}
