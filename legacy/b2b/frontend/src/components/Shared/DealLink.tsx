import { Button } from '@/components/ui/button';

/**
 * Clickable "#<dealId>" that navigates to the buyer's request detail. Billing
 * tables (contracts / invoices / payments / fulfillments) all reference a deal
 * by number; without this the number was dead text and the buyer had no path
 * from a financial record back to the underlying заявка. stopPropagation so it
 * works inside clickable rows.
 */
export function DealLink({ dealId, className }: { dealId: number; className?: string }) {
  return (
    <Button
      variant="link"
      className={`h-auto p-0 font-medium tabular-nums ${className ?? ''}`}
      onClick={(e) => { e.stopPropagation(); window.location.hash = `request-detail/${dealId}`; }}
    >
      #{dealId}
    </Button>
  );
}
