import { Button, Tooltip } from "antd";
import type { ButtonProps } from "antd";
import { useTranslation } from "react-i18next";

/**
 * Кнопка действия, которого ещё нет (PLT-12: главные действия модулей появятся в фазе P2). Неактивна, с подсказкой;
 * доступное имя несёт пояснение, потому что неактивную кнопку нельзя навести клавиатурой.
 */
export function SoonButton({
  children,
  hint,
  ...props
}: Omit<ButtonProps, "disabled" | "aria-label"> & { hint?: string }) {
  const { t } = useTranslation("shell");
  const text = hint ?? t("soon");
  const label = typeof children === "string" ? children : undefined;
  return (
    <Tooltip title={text}>
      <span style={{ display: props.block ? "block" : "inline-block" }}>
        <Button
          {...props}
          disabled
          aria-label={label ? `${label}. ${text}` : undefined}
          style={{ ...props.style, pointerEvents: "none" }}
        >
          {children}
        </Button>
      </span>
    </Tooltip>
  );
}
