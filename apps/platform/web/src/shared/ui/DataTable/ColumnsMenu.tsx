import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  MinusOutlined,
  PlusOutlined,
  PushpinFilled,
  PushpinOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Popover } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

interface MenuColumn {
  id: string;
  header: string;
  canHide: boolean;
}

export interface ColumnsMenuProps {
  columns: readonly MenuColumn[];
  /** Порядок всех столбцов экрана */
  order: readonly string[];
  hidden: readonly string[];
  pinned: readonly string[];
  /** Есть ли у сотрудника свои настройки (иначе «Сбросить» неактивна) */
  changed: boolean;
  onOrder: (order: string[]) => void;
  onHidden: (hidden: string[]) => void;
  onPinned: (pinned: string[]) => void;
  /** Ширина с клавиатуры: −1 — уже, +1 — шире */
  onWidth: (id: string, delta: number) => void;
  onReset: () => void;
}

/**
 * «Столбцы» над таблицей (пункт «Т»): флажок — видимость (первый столбец всегда виден), стрелки — порядок, булавка —
 * закрепить слева (столбец остаётся на месте при прокрутке вбок), «−»/«+» — ширина с клавиатуры (мышью — за границу
 * заголовка), «Сбросить» — вид по умолчанию, включая ширину.
 */
export function ColumnsMenu({
  columns,
  order,
  hidden,
  pinned,
  changed,
  onOrder,
  onHidden,
  onPinned,
  onWidth,
  onReset,
}: ColumnsMenuProps) {
  const { t } = useTranslation("ui");
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const byId = new Map(columns.map((column) => [column.id, column]));
  const list = order
    .map((id) => byId.get(id))
    .filter((column): column is MenuColumn => Boolean(column));

  const move = (id: string, delta: number) => {
    const next = [...order];
    const from = next.indexOf(id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= next.length) return;
    next.splice(from, 1);
    next.splice(to, 0, id);
    onOrder(next);
  };

  const content = (
    <div className="pf-dt-menu" role="group" aria-labelledby={titleId}>
      <p id={titleId} className="pf-dt-menu-title">
        {t("table.columns")}
      </p>
      <ul className="pf-dt-menu-list">
        {list.map((column, index) => {
          const isPinned = pinned.includes(column.id);
          return (
            <li key={column.id} className="pf-dt-menu-item">
              <Checkbox
                checked={!hidden.includes(column.id)}
                disabled={!column.canHide}
                onChange={(event) => {
                  onHidden(
                    event.target.checked
                      ? hidden.filter((id) => id !== column.id)
                      : [...hidden, column.id],
                  );
                }}
              >
                {column.header}
              </Checkbox>
              <span className="pf-dt-menu-actions">
                <Button
                  type="text"
                  size="small"
                  icon={isPinned ? <PushpinFilled /> : <PushpinOutlined />}
                  aria-pressed={isPinned}
                  aria-label={t(isPinned ? "table.unpin" : "table.pin", { name: column.header })}
                  title={t(isPinned ? "table.unpin" : "table.pin", { name: column.header })}
                  onClick={() => {
                    onPinned(
                      isPinned ? pinned.filter((id) => id !== column.id) : [...pinned, column.id],
                    );
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<MinusOutlined />}
                  aria-label={t("table.narrower", { name: column.header })}
                  title={t("table.narrower", { name: column.header })}
                  onClick={() => {
                    onWidth(column.id, -1);
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<PlusOutlined />}
                  aria-label={t("table.wider", { name: column.header })}
                  title={t("table.wider", { name: column.header })}
                  onClick={() => {
                    onWidth(column.id, 1);
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={index === 0}
                  aria-label={t("table.moveUp", { name: column.header })}
                  title={t("table.moveUp", { name: column.header })}
                  onClick={() => {
                    move(column.id, -1);
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={index === list.length - 1}
                  aria-label={t("table.moveDown", { name: column.header })}
                  title={t("table.moveDown", { name: column.header })}
                  onClick={() => {
                    move(column.id, 1);
                  }}
                />
              </span>
            </li>
          );
        })}
      </ul>
      <Button
        size="small"
        disabled={!changed}
        onClick={() => {
          onReset();
        }}
      >
        {t("table.reset")}
      </Button>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      placement="bottomRight"
      open={open}
      onOpenChange={setOpen}
    >
      <Button size="small" type="text" icon={<SettingOutlined aria-hidden />} aria-expanded={open}>
        {t("table.columns")}
      </Button>
    </Popover>
  );
}
