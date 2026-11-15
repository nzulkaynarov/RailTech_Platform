import { Button, theme } from "antd";
import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import "./ui.css";

/**
 * Панель выбора (стандарт интерфейса §7): «Выбрано: N», массовые действия и «Снять выбор» — всплывает внизу списка, пока
 * выбрана хотя бы одна строка. Ничего не выбрано — панели нет. Действия — кнопки экрана (`children`); опасное — в конце.
 */
export function SelectionBar({
  count,
  label,
  onClear,
  children,
}: {
  count: number;
  /** Имя области для экранного чтеца, например «Выбранные письма» */
  label: string;
  onClear: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("ui");
  const { token } = theme.useToken();
  if (count === 0) return null;
  return (
    <div
      className="pf-selection-bar"
      role="region"
      aria-label={label}
      style={{ "--pf-selection-shadow": token.boxShadowSecondary } as CSSProperties}
    >
      <span className="pf-selection-count" aria-live="polite">
        {t("selection.count", { count })}
      </span>
      <span className="pf-selection-actions">{children}</span>
      <Button type="link" onClick={onClear}>
        {t("selection.clear")}
      </Button>
    </div>
  );
}
