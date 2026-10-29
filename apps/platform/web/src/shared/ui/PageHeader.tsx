import { Button, Dropdown, theme } from "antd";
import type { MenuProps } from "antd";
import { MoreOutlined } from "@ant-design/icons";
import React, { Children, isValidElement, type ReactNode } from "react";

export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  extra?: ReactNode;
  /** Главное целевое действие (макс. 1) */
  primaryAction?: ReactNode;
  /** Второстепенные действия (макс. 2) */
  secondaryActions?: ReactNode[];
  /** Действия, скрытые в выпадающее меню Dropdown (MoreOutlined) */
  moreActions?: MenuProps["items"];
}

/**
 * Стандартизированный заголовок страницы (docs/architecture/platform-frontend.md §4).
 * В блоке extra: не более 1 главной кнопки и 1-2 второстепенных;
 * остальные действия группируются в Dropdown (MoreOutlined), предотвращая перенос на вторую строку.
 */
export function PageHeader({
  title,
  subtitle,
  extra,
  primaryAction,
  secondaryActions,
  moreActions,
}: PageHeaderProps) {
  const { token } = theme.useToken();

  // Если переданы структурированные действия
  const hasStructuredActions = Boolean(
    primaryAction || secondaryActions?.length || moreActions?.length,
  );

  const renderExtra = () => {
    if (hasStructuredActions) {
      return (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexShrink: 0,
            flexWrap: "nowrap",
          }}
        >
          {secondaryActions?.slice(0, 2).map((action, idx) => (
            <React.Fragment key={idx}>{action}</React.Fragment>
          ))}
          {primaryAction}
          {moreActions && moreActions.length > 0 ? (
            <Dropdown menu={{ items: moreActions }} trigger={["click"]} placement="bottomRight">
              <Button icon={<MoreOutlined />} aria-label="Дополнительные действия" />
            </Dropdown>
          ) : null}
        </div>
      );
    }

    if (!extra) return null;

    // Если в extra передан массив или фрагмент с несколькими элементами (> 3 кнопок),
    // стандартизируем их отображение в 1 строку без переноса
    const extraChildren = Children.toArray(extra).filter(isValidElement);
    if (extraChildren.length > 3) {
      const visible = extraChildren.slice(0, 2);
      const overflow = extraChildren.slice(2);
      const overflowMenuItems: MenuProps["items"] = overflow.map((child, idx) => ({
        key: "overflow-" + String(idx),
        label: child,
      }));

      return (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexShrink: 0,
            flexWrap: "nowrap",
          }}
        >
          {visible.map((child, idx) => (
            <React.Fragment key={idx}>{child}</React.Fragment>
          ))}
          <Dropdown menu={{ items: overflowMenuItems }} trigger={["click"]} placement="bottomRight">
            <Button icon={<MoreOutlined />} aria-label="Дополнительные действия" />
          </Dropdown>
        </div>
      );
    }

    return (
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, flexWrap: "nowrap" }}
      >
        {extra}
      </div>
    );
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        minHeight: 40,
        marginBottom: 16,
        padding: "4px 0",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <h1 style={{ margin: 0, fontSize: 20, lineHeight: "28px", fontWeight: 600 }}>{title}</h1>
        {subtitle ? <div style={{ color: token.colorTextSecondary }}>{subtitle}</div> : null}
      </div>
      {renderExtra()}
    </div>
  );
}
