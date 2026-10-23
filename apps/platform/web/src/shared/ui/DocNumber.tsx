import { Link } from "react-router";

import { docNumberToPath } from "../lib/docNumber";
import "./ui.css";

/**
 * Бизнес-номер объекта (`ПР-2026-104`): не переносится по строкам, цифры одной ширины, не переводится автопереводчиком.
 * С `base` — ссылка на карточку: `<base>/<номер в кодировке URL>` (SPEC-v3 §6.3, docs/architecture/platform-frontend.md §6).
 */
export function DocNumber({ number, base }: { number: string; base?: string }) {
  const content = (
    <span className="pf-docnum" translate="no">
      {number}
    </span>
  );
  return base ? (
    <Link to={`${base.replace(/\/$/, "")}/${docNumberToPath(number)}`} className="pf-link">
      {content}
    </Link>
  ) : (
    content
  );
}
