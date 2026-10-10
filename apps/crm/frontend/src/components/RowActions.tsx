import { MoreOutlined } from "@ant-design/icons";
import { Button, Dropdown } from "antd";
import type { ReactNode } from "react";

import { t } from "../i18n/ru";

export type RowAction = {
  key: string;
  label: ReactNode;
  onClick: () => void;
  /** Красным — только внутри меню; подтверждение — у вызывающего (useConfirmDanger). */
  danger?: boolean;
  disabled?: boolean;
};

/**
 * Действия строки таблицы одним меню «⋯» вместо ряда кнопок (дизайн-аудит 2026-10-11:
 * «одно частое действие видимо + меню для остальных»). `label` — имя кнопки для скринридера.
 */
export function RowActions({ label, actions }: { label: string; actions: RowAction[] }) {
  if (!actions.length) return null;
  return (
    <Dropdown
      trigger={["click"]}
      menu={{
        items: actions.map((a) => ({
          key: a.key,
          label: a.label,
          danger: a.danger ?? false,
          disabled: a.disabled ?? false,
        })),
        onClick: ({ key, domEvent }) => {
          domEvent.stopPropagation();
          actions.find((a) => a.key === key)?.onClick();
        },
      }}
    >
      <Button type="text" size="small" icon={<MoreOutlined />} aria-label={label} />
    </Dropdown>
  );
}

/** Колонка действий: заголовок есть, но виден только скринридеру (axe empty-table-header). */
export const ActionsTitle = () => <span className="sr-only">{t.common.actions}</span>;
