import { Button, Dropdown } from "antd";
import { useTranslation } from "react-i18next";

import { MoreIcon } from "./lucide";

export interface RowAction {
  key: string;
  label: string;
  onClick: () => void;
  /** Опасное действие (удалить, отозвать) — красным, отделено чертой от остальных */
  danger?: boolean;
  disabled?: boolean;
}

/** Ширина столбца меню строки: кнопка 24 и поля ячейки. */
export const ROW_ACTIONS_WIDTH = 56;

/**
 * Меню строки «…» (стандарт интерфейса §7): действия над строкой реестра — одной кнопкой в последнем столбце, а не
 * рядом кнопок. Открытие строки — по её названию или стрелке, в меню — остальное («Изменить», «Скопировать», «Удалить»).
 * Опасные действия — в конце, после черты. Нет доступных действий — кнопки нет.
 */
export function RowActions({ name, items }: { name: string; items: readonly RowAction[] }) {
  const { t } = useTranslation("ui");
  const shown = items.filter((item) => !item.disabled);
  if (shown.length === 0) return null;
  const safe = shown.filter((item) => !item.danger);
  const danger = shown.filter((item) => item.danger);
  const menu = [
    ...safe.map((item) => ({ key: item.key, label: item.label })),
    ...(safe.length > 0 && danger.length > 0 ? [{ type: "divider" as const }] : []),
    ...danger.map((item) => ({ key: item.key, label: item.label, danger: true })),
  ];
  return (
    <Dropdown
      trigger={["click"]}
      placement="bottomRight"
      menu={{
        items: menu,
        onClick: ({ key, domEvent }) => {
          domEvent.stopPropagation();
          shown.find((item) => item.key === key)?.onClick();
        },
      }}
    >
      <Button
        type="text"
        size="small"
        icon={<MoreIcon />}
        aria-label={t("rowActions.label", { name })}
        onClick={(event) => {
          event.stopPropagation();
        }}
      />
    </Dropdown>
  );
}
