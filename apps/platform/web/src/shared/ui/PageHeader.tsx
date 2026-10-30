import { theme } from "antd";
import type { ReactNode } from "react";

/** Заголовок страницы основного окна: 20/600 (строка 28) и подзаголовок `#595959` (docs/architecture/platform-frontend.md §4). */
export function PageHeader({
  title,
  subtitle,
  extra,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  extra?: ReactNode;
}) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <h1 style={{ margin: 0, fontSize: 20, lineHeight: "28px", fontWeight: 600 }}>{title}</h1>
        {subtitle ? <div style={{ color: token.colorTextSecondary }}>{subtitle}</div> : null}
      </div>
      {extra ? <div>{extra}</div> : null}
    </div>
  );
}
