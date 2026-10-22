import { Button } from "antd";
import type { ButtonProps } from "antd";
import type { MouseEvent } from "react";
import { useNavigate } from "react-router";

/** Ссылка в виде кнопки: настоящий `<a href>` (открывается в новой вкладке), переход по клику — без перезагрузки. */
export function LinkButton({ to, children, ...props }: Omit<ButtonProps, "href"> & { to: string }) {
  const navigate = useNavigate();
  const onClick = (event: MouseEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    void navigate(to);
  };
  return (
    <Button {...props} href={to} onClick={onClick}>
      {children}
    </Button>
  );
}
