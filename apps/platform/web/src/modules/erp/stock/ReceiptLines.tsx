import { useFormat } from "../../../shared/lib/useFormat";
import type { ItemRef } from "../../../shared/api/generated/model";
import { ItemRefCell } from "../../ItemRefCell";
import { withUnit } from "./api";

interface ReceiptLine {
  order_line_id?: string;
  name: string;
  item: ItemRef | null;
  quantity: number;
  cell: string | null;
}

/**
 * Строки принятой поставки (ЕД-4): позиция — миниатюра, название, наш артикул (`ItemRefCell`), справа количество и ячейка.
 * Общий вид для журнала приёмок склада и приёмок на экране заказа.
 */
export function ReceiptLines<L extends ReceiptLine>({
  lines,
  unitOf,
}: {
  lines: readonly L[];
  /** Единица измерения строки заказа, если известна */
  unitOf?: (line: L) => string | null | undefined;
}) {
  const { qty } = useFormat();
  return (
    <ul className="pf-stock-receipt-lines">
      {lines.map((l, index) => (
        <li key={`${l.name}:${String(index)}`}>
          <ItemRefCell item={l.item} name={l.name} />
          <span className="pf-hint pf-num">
            {withUnit(qty(l.quantity), unitOf?.(l))}
            {l.cell ? ` (${l.cell})` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
