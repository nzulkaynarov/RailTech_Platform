import { Button, Tooltip } from "antd";
import type { ButtonProps } from "antd";
import { useTranslation } from "react-i18next";

/**
 * Кнопка действия, которого ещё нет (PLT-12: главные действия модулей появятся в фазе P2). Неактивна, с подсказкой;
 * доступное имя несёт пояснение, потому что неактивную кнопку нельзя навести клавиатурой.
 */
export function SoonButton({ children, ...props }: Omit<ButtonProps, "disabled" | "aria-label">) {
  const { t } = useTranslation("shell");
  const label = typeof children === "string" ? children : undefined;
  return (
    <Tooltip title={t("soon")}>
      <span style={{ display: props.block ? "block" : "inline-block" }}>
        <Button
          {...props}
          disabled
          aria-label={label ? `${label}. ${t("soon")}` : undefined}
          style={{ ...props.style, pointerEvents: "none" }}
        >
          {children}
        </Button>
      </span>
    </Tooltip>
  );
}
