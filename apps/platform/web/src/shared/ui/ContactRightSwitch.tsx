import { Switch } from "antd";
import type { ReactNode } from "react";

import "./contact-right.css";

/**
 * «Может подтверждать» контакта (КЛИЕНТ-1): один переключатель для партнёра и клиента. Без права контакт в Кабинете только
 * смотрит; правится сразу. Подписи и действие даёт вызывающий — у партнёра и клиента разные запросы к ERP.
 */
export function ContactRightSwitch({
  checked,
  editable,
  pending = false,
  label,
  ariaLabel,
  error,
  onChange,
}: {
  checked: boolean;
  editable: boolean;
  pending?: boolean;
  label: string;
  ariaLabel: string;
  error?: ReactNode;
  onChange: (on: boolean) => void;
}) {
  return (
    <div className="pf-contact-right">
      <Switch
        checked={checked}
        disabled={!editable || pending}
        aria-label={ariaLabel}
        onChange={onChange}
      />
      <span aria-hidden="true">{label}</span>
      {error}
    </div>
  );
}
