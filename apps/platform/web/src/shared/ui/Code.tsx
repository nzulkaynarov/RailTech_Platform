import type { ReactNode } from "react";

import "./ui.css";

/**
 * Код или номер моноширинным шрифтом (стандарт интерфейса §3): артикул, серийный номер, ТН ВЭД и МХИК, ИНН,
 * расчётный счёт и МФО, номера сделок и документов. Не переносится и не переводится автопереводчиком. `quiet` — вторая
 * строка ячейки «название и код»: 12 px приглушённым цветом.
 */
export function Code({ children, quiet = false }: { children: ReactNode; quiet?: boolean }) {
  return (
    <span className={quiet ? "pf-code pf-code--quiet" : "pf-code"} translate="no">
      {children}
    </span>
  );
}
