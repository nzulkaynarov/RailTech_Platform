import { Card, theme } from "antd";
import type { ReactNode } from "react";

/** Рамка экранов вне каркаса (вход, смена пароля): карточка 400 px по центру на фоне `#f5f5f5`. */
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
        <div
          aria-hidden="true"
          style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            background: token.colorPrimary,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          RT
        </div>
        <h1 style={{ margin: 0, fontSize: 20, lineHeight: "28px", fontWeight: 600 }}>{title}</h1>
        {lead ? <p style={{ margin: "4px 0 0", color: token.colorTextSecondary }}>{lead}</p> : null}
        <div style={{ marginTop: 24 }}>{children}</div>
      </Card>
    </main>
  );
}
