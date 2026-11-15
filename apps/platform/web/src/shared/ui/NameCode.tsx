import type { ReactNode } from "react";

import { Code } from "./Code";

/**
 * Ячейка «название и код» (стандарт интерфейса §7): название сверху, под ним код приглушённым моноширинным — артикул,
 * номер заявки, код значения. `codeLabel` озвучивается перед кодом для чтения с экрана. Нет кода — только название.
 */
export function NameCode({
  name,
  code,
  codeLabel,
}: {
  name: ReactNode;
  code?: string | null;
  codeLabel?: string;
}) {
  return (
    <>
      <div>{name}</div>
      {code ? (
        <div className="pf-ell">
          {codeLabel ? <span className="pf-sr-only">{codeLabel}: </span> : null}
          <Code quiet>{code}</Code>
        </div>
      ) : null}
    </>
  );
}
