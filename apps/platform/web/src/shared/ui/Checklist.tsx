import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { statusStyle } from "../lib/statuses";
import { CheckIcon, CrossIcon, MinusIcon } from "./icons";
import "./ui.css";

export type CheckState = "ok" | "fail" | "pending";

export interface ChecklistItem {
  state: CheckState;
  label: ReactNode;
  /** Дата и автор: «Азиз · 22.10» */
  meta?: ReactNode;
}

/** Значок пункта; цвет — карта `check` (`STATUS_TONE`, UX-2b). */
const ICON: Record<CheckState, ReactNode> = {
  ok: <CheckIcon />,
  fail: <CrossIcon />,
  pending: <MinusIcon />,
};

/**
 * Чек-лист одобрения КП (docs/architecture/platform-frontend.md §5): строки 13 px, отступ 8/0, граница `#f0f0f0`, значок-статус (галочка,
 * крестик, тире — форма, а не только цвет, плюс слово для скринридера), справа дата и автор.
 */
export function Checklist({ items, label }: { items: readonly ChecklistItem[]; label?: string }) {
  const { t } = useTranslation("ui");
  return (
    <ul className="pf-list" aria-label={label}>
      {items.map((item, index) => {
        return (
          <li key={index} className="pf-check">
            <span
              className="pf-check-chip"
              style={statusStyle("check", item.state)}
              aria-hidden="true"
            >
              {ICON[item.state]}
            </span>
            <span className="pf-check-label">
              <span className="pf-sr-only">{t(`checklist.${item.state}`)}: </span>
              {item.label}
            </span>
            {item.meta ? <span className="pf-hint">{item.meta}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}
