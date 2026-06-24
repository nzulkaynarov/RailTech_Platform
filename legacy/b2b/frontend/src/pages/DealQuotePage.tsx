import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, FileText, Send, FileSignature, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { StatusBadge, getDealStageVariant } from '@/components/ui/StatusBadge';
import { useCurrencyStore } from '@/store/currencyStore';
import { useDeal, useSendQuoteToClient } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { QuoteBuilderGrid } from '@/components/Admin/QuoteBuilderGrid';
import { GenerateContractDialog } from '@/components/CRM/GenerateContractDialog';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { QuoteStatus, DEAL_STAGE_LABEL_KEY } from '@/lib/codes';
import { LoadingRows, EmptyState } from './shared/PageShell';

interface DealQuotePageProps {
  dealId: number;
  onBack: () => void;
}

/**
 * Full-page seller КП (quote) builder. Replaces the cramped in-sheet builder:
 * the wide line-item/price grid + approval chain need the whole viewport, not a
 * side panel. Reached via the `deal-quote/<dealId>` hash route from DealsPage.
 * State is React Query throughout (useDeal / useCRM) — no flowStore.
 */
export function DealQuotePage({ dealId, onBack }: DealQuotePageProps) {
  const { t } = useTranslation();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const { data: deal, isLoading, isError, refetch } = useDeal(dealId);
  const sendQuote = useSendQuoteToClient();
  const [contractOpen, setContractOpen] = useState(false);
  const [sendConfirmOpen, setSendConfirmOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <LoadingRows rows={6} />
      </div>
    );
  }

  // A failed fetch must read as an error with a way out — not the same
  // "not found" empty state that an actually-missing deal would show.
  if (isError && !deal) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
          <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
        </div>
        <p className="text-sm font-medium">{t('common.loadError')}</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>{t('common.retry')}</Button>
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ArrowLeft className="mr-1.5 h-4 w-4" />
            {t('common.back')}
          </Button>
        </div>
      </div>
    );
  }

  if (!deal) {
    return (
      <EmptyState
        icon={<FileText className="h-5 w-5" />}
        message={t('pages.dealQuote.notFound')}
        action={{ label: t('common.back'), onClick: onBack }}
      />
    );
  }

  const quote = deal.active_quote;
  const quoteStatus = quote?.status_code ?? '';
  // Once the КП is internally approved (READY_TO_SEND) the seller pushes it to
  // the client — the final документооборот step. Contract generation unlocks
  // once the КП is sent/approved.
  const canSend = quoteStatus === QuoteStatus.READY_TO_SEND;
  const canContract = !!quote
    && ([QuoteStatus.APPROVED, QuoteStatus.SENT] as string[]).includes(quoteStatus);

  // Sending the КП is irreversible and client-visible (the buyer immediately
  // sees the priced offer + frozen prices) → gate behind a confirm dialog.
  const confirmSend = async () => {
    if (!quote) return;
    await sendQuote.mutateAsync(quote.id);
    toast.success(t('pages.deals.detail.quoteSentToast'));
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header: back + deal context + seller lifecycle actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack} aria-label={t('common.back')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileText className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t('pages.dealQuote.title')}</h1>
            <p className="text-sm text-muted-foreground">
              {deal.title || `${t('pages.deals.deal')} #${deal.id}`}
              {(deal.client_name || deal.company_name)
                ? ` · ${deal.client_name || deal.company_name}`
                : ''}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge
            label={deal.stage_code && DEAL_STAGE_LABEL_KEY[deal.stage_code]
              ? t(DEAL_STAGE_LABEL_KEY[deal.stage_code])
              : (deal.stage_name ?? '')}
            variant={getDealStageVariant(deal.stage_code ?? '')}
          />
          {deal.total_value ? (
            <span className="text-sm font-semibold tabular-nums">
              {formatCurrency(Number(deal.total_value))}
            </span>
          ) : null}
          {canSend && (
            <Button size="sm" disabled={sendQuote.isPending} onClick={() => setSendConfirmOpen(true)}>
              <Send className="mr-2 h-4 w-4" />
              {t('requestDetailActions.sendQuote')}
            </Button>
          )}
          {canContract && (
            <Button size="sm" variant="outline" onClick={() => setContractOpen(true)}>
              <FileSignature className="mr-2 h-4 w-4" />
              {t('contractGenerateDialog.generate')}
            </Button>
          )}
        </div>
      </div>

      {/* Builder — full width/height. QuoteBuilderGrid renders its own approval
          chain bar + toolbar + summary footer; it only needs a tall container. */}
      {quote ? (
        <div className="h-[calc(100vh-14rem)] min-h-[520px]">
          <QuoteBuilderGrid dealId={dealId} />
        </div>
      ) : (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          message={t('pages.dealQuote.noQuote')}
          hint={t('pages.dealQuote.noQuoteHint')}
          action={{ label: t('common.back'), onClick: onBack }}
        />
      )}

      <GenerateContractDialog
        quoteId={quote?.id ?? null}
        open={contractOpen}
        onOpenChange={setContractOpen}
      />

      <ConfirmActionDialog
        open={sendConfirmOpen}
        onOpenChange={setSendConfirmOpen}
        title={t('confirmActions.sendQuote.title')}
        description={t('confirmActions.sendQuote.description')}
        variant="primary"
        confirmLabel={t('requestDetailActions.sendQuote')}
        onConfirm={confirmSend}
        translateError={(code) => translateApiError(code)}
      />
    </div>
  );
}

export default DealQuotePage;
