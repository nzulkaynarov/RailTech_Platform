import type { DeliveryLine } from '@/api/portal';

/** Строки поставки по сделкам — в порядке первого появления сделки в ответе ERP, строки по `line_no`. */
export interface DeliveryGroup {
  dealId: number;
  lines: DeliveryLine[];
  delivered: number;
}

export function groupDeliveries(lines: DeliveryLine[]): DeliveryGroup[] {
  const groups = new Map<number, DeliveryLine[]>();
  for (const line of lines) {
    const bucket = groups.get(line.deal_id);
    if (bucket) bucket.push(line);
    else groups.set(line.deal_id, [line]);
  }
  return Array.from(groups, ([dealId, items]) => {
    const sorted = [...items].sort((a, b) => a.line_no - b.line_no);
    return { dealId, lines: sorted, delivered: sorted.filter((line) => line.status === 'delivered').length };
  });
}
