import { useState } from 'react';
import { toast } from 'sonner';
import type { Deal, Quote, PreflightFinding, PreflightLine } from '@/api/crmApi';
import { usePreflightCheck } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { RequestItemsEditor } from '@/components/CRM/RequestItemsEditor';
import { PreflightWarnings } from '@/components/CRM/PreflightWarnings';

/**
 * Buyer-editable request surface: the request lines (name + qty, NO price) plus the AI #7
 * advisory pre-flight quality check. The check is purely advisory — it never gates submitting
 * the RFQ — and only appears once there are lines to inspect.
 */
export function BuyerRequestEditor({ deal, quote }: { deal: Deal; quote: Quote | null }) {
  // AI #7 pre-flight advisory state (DRAFT buyer request only).
  const [preflightFindings, setPreflightFindings] = useState<PreflightFinding[]>([]);
  const [preflightRan, setPreflightRan] = useState(false);
  const preflightCheck = usePreflightCheck();

  // Map the buyer's draft request lines → the advisory pre-flight check payload. Only the
  // buyer-owned fields travel (no price); the backend validates indices.
  const preflightLines: PreflightLine[] = (quote?.items ?? []).map((item) => ({
    name: item.product_name || item.imported_raw_name || '',
    quantity: item.quantity,
    unit: item.unit,
    mpn: item.mpn,
    gost_drawing: item.gost_drawing,
    note: item.note,
  }));

  const handlePreflightCheck = () => {
    preflightCheck.mutate(
      { lines: preflightLines },
      {
        onSuccess: (data) => {
          setPreflightFindings(data.findings);
          setPreflightRan(true);
        },
        onError: (err) => {
          // AI off → 503 AI_DISABLED; surface a friendly toast, never a crash.
          toast.error(translateApiError(err));
        },
      },
    );
  };

  return (
    <>
      <RequestItemsEditor
        dealId={deal.id}
        items={quote?.items ?? []}
        canEdit
        hasRecipients={(deal.target_sellers_data?.length ?? 0) > 0}
      />
      {preflightLines.length > 0 && (
        <PreflightWarnings
          lines={preflightLines}
          findings={preflightFindings}
          isPending={preflightCheck.isPending}
          hasRun={preflightRan}
          onCheck={handlePreflightCheck}
        />
      )}
    </>
  );
}

export default BuyerRequestEditor;
