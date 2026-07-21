import { useTranslation } from 'react-i18next';
import { CheckCircle2, FileSignature, Loader2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useContracts } from '@/hooks/useBilling';
import type { Contract } from '@/api/contractsApi';

/**
 * Post-accept "what's next" panel (Wave A2). After a buyer approves the КП the FSM
 * auto-materializes a Contract (status PENDING_CLIENT) that awaits their signature.
 * Instead of bouncing to the dashboard, keep the buyer on the request surface and
 * point them straight at that contract.
 *
 * The contract number/id are read from the LIVE API (`useContracts({ deal })`) — never
 * fabricated. `useApproveQuote` invalidates ['contracts'], so this query resolves the
 * freshly-created contract; the CTA deep-links to it on the Contracts page
 * (`#contracts?open=<id>`, read by ContractsPage).
 */
export function BuyerAcceptedPanel({ dealId }: { dealId: number }) {
  const { t } = useTranslation();
  const { data: contracts, isLoading } = useContracts({ deal: dealId });

  // The contract for this deal: skip a CANCELLED one, newest first.
  const contract: Contract | null =
    (contracts ?? [])
      .filter((c) => c.status !== 'CANCELLED')
      .sort((first, second) => (second.created_at ?? '').localeCompare(first.created_at ?? ''))[0] ?? null;

  const awaitingClient = contract?.status === 'PENDING_CLIENT';
  const resolving = isLoading && !contract;

  const goToContract = () => {
    window.location.hash = contract ? `contracts?open=${contract.id}` : 'contracts';
  };

  const detail = resolving
    ? t('requestDetailActions.accepted.resolving')
    : contract
      ? awaitingClient
        ? t('requestDetailActions.accepted.readyToSign', { number: contract.number })
        : t('requestDetailActions.accepted.contractReady', { number: contract.number })
      : t('requestDetailActions.accepted.contractPending');

  return (
    <Card className="border-success/30 bg-success/5">
      <CardContent className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-success" aria-hidden="true" />
          <div className="space-y-1">
            <p className="text-sm font-semibold">{t('requestDetailActions.accepted.title')}</p>
            <p className="text-sm text-muted-foreground">{detail}</p>
          </div>
        </div>
        <Button className="shrink-0 gap-2" onClick={goToContract} disabled={resolving}>
          {resolving
            ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            : <FileSignature className="h-4 w-4" aria-hidden="true" />}
          {t('requestDetailActions.accepted.goToContract')}
        </Button>
      </CardContent>
    </Card>
  );
}

export default BuyerAcceptedPanel;
