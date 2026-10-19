import type { DealRef, DeliveryLine } from '@/api/portal';

/** Строки поставки по сделкам — в порядке первого появления сделки в ответе ERP, строки по `line_no`. */
export interface DeliveryGroup {
  deal: DealRef;
  lines: DeliveryLine[];
  /** Доставлено клиенту: `delivered` и уже принятые или оспоренные им строки. */
  delivered: number;
}

const RECEIVED: ReadonlyArray<DeliveryLine['status']> = ['delivered', 'accepted', 'disputed'];

export function groupDeliveries(lines: DeliveryLine[]): DeliveryGroup[] {
  const groups = new Map<number, { deal: DealRef; items: DeliveryLine[] }>();
  for (const line of lines) {
    const bucket = groups.get(line.deal.id);
    if (bucket) bucket.items.push(line);
    else groups.set(line.deal.id, { deal: line.deal, items: [line] });
  }
  return Array.from(groups.values(), ({ deal, items }) => {
    const sorted = [...items].sort((a, b) => a.line_no - b.line_no);
    return { deal, lines: sorted, delivered: sorted.filter((line) => RECEIVED.includes(line.status)).length };
  });
}
