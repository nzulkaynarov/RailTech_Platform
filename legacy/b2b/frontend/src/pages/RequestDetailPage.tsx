import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Send, Calculator, ThumbsUp, ThumbsDown, User, Briefcase } from 'lucide-react';
import { toast } from 'sonner';
import { QuoteStatus, DealStage } from '@/lib/codes';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { useDeal, useChangeDealStage, useApproveQuote, useRejectQuote, useSendQuoteToClient } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { LoadingSkeleton } from '@/components/LoadingSkeleton';
import { DealChatPanel } from '@/components/Sourcing/DealChatPanel';
import { RejectQuoteDialog } from '@/components/CRM/RejectQuoteDialog';

/**
 * Canonical buyer-facing deal/КП detail surface. Reached via the
 * `request-detail/<dealId>` hash route (My Requests / Sourcing / cart / import).
 * State is React Query throughout (useDeal + useCRM) — the old Zustand
 * `flowStore` flow was retired. Seller-side stage actions remain for sellers who
 * land here from the sourcing list; the buyer only ever sees approve/reject.
 */
export function RequestDetailPage({ dealId, onBack }: { dealId: number; onBack: () => void }) {
  const { t } = useTranslation();
  const { data: deal, isLoading } = useDeal(dealId);
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [rejectOpen, setRejectOpen] = useState(false);
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');

  const changeStage = useChangeDealStage();
  const approveQuote = useApproveQuote();
  const rejectQuote = useRejectQuote();
  const sendQuote = useSendQuoteToClient();

  // Gate seller-side actions (start sourcing / calculation / send quote) to
  // sellers. A buyer would only hit backend guards — and the buttons are
  // meaningless on their screen.
  const activeStatus = useUserStore((s) => s.activeStatus);
  const isSellerSide = activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER';
  const isBuyerSide = activeStatus === 'BUYER';

  if (isLoading && !deal) return <LoadingSkeleton />;
  if (!deal) return <div className="p-8 text-center text-muted-foreground">{t('pages.common.noData')}</div>;

  const quote = deal.active_quote ?? deal.quotes?.[deal.quotes.length - 1] ?? null;

  const isDraft = deal.stage_code === DealStage.DRAFT;
  const isSourcing = deal.stage_code === DealStage.SOURCING;
  const isCalculating = deal.stage_code === DealStage.CALCULATING;
  const isQuoteSent = deal.stage_code === DealStage.QUOTE_SENT;
  const isWon = deal.stage_code === DealStage.CLOSED_WON || deal.stage_code === DealStage.CONTRACT_SIGNED;

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <div className="flex gap-4">
      <div className="flex flex-col gap-6 flex-[7] min-w-0">

        {/* Header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack}><ArrowLeft className="h-4 w-4" /></Button>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold">{deal.title || `#${deal.id}`}</h1>
              <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20">
                {deal.stage_name}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-2">
              <Briefcase className="h-3.5 w-3.5" />
              {deal.client_name || deal.company_name}
              {deal.manager_name && (
                <>
                  <span className="text-border">|</span>
                  <User className="h-3.5 w-3.5" />
                  {deal.manager_name}
                </>
              )}
            </p>
          </div>
        </div>

        {/* Action Bar. Seller-side actions (start sourcing / start calculation
            / send quote) only show for SELLER / MANUFACTURER. Buyer only sees
            approve / reject once the quote is sent. */}
        {(() => {
          const sellerActions = isSellerSide && (isDraft || isSourcing || (isCalculating && quote));
          const buyerActions = isBuyerSide && isQuoteSent && quote;
          const showActionBar = sellerActions || buyerActions || isWon;
          if (!showActionBar) {
            return (
              <Card className="bg-muted/30">
                <CardContent className="py-4">
                  <span className="text-sm text-muted-foreground">
                    {isBuyerSide
                      ? t('requestDetailActions.buyerWaitHint')
                      : t('requestDetailActions.noActions')}
                  </span>
                </CardContent>
              </Card>
            );
          }
          return (
            <Card className="bg-muted/30">
              <CardContent className="flex items-center gap-3 py-4">
                <span className="text-sm font-medium">{t('requestDetailActions.actionsLabel')}:</span>
                {isSellerSide && isDraft && (
                  <Button
                    variant="default"
                    onClick={() => run(() => changeStage.mutateAsync({ id: deal.id, stage: DealStage.SOURCING }))}
                    disabled={isViewer || changeStage.isPending}
                    title={isViewer ? viewerTip : undefined}
                  >
                    {t('requestDetailActions.startSourcing')}
                  </Button>
                )}
                {isSellerSide && isSourcing && (
                  <Button
                    variant="default"
                    onClick={() => run(() => changeStage.mutateAsync({ id: deal.id, stage: DealStage.CALCULATING }))}
                    disabled={isViewer || changeStage.isPending}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <Calculator className="h-4 w-4 mr-2" />
                    {t('requestDetailActions.startCalculation')}
                  </Button>
                )}
                {/* Only an internally-approved КП can be sent (backend requires
                    READY_TO_SEND). Getting there is done via the approval chain on
                    the Deals page; this stays disabled until then. */}
                {isSellerSide && quote?.status_code === QuoteStatus.READY_TO_SEND && (
                  <Button
                    variant="default"
                    onClick={() => run(() => sendQuote.mutateAsync(quote.id))}
                    disabled={isViewer || sendQuote.isPending}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <Send className="h-4 w-4 mr-2" />
                    {t('requestDetailActions.sendQuote')}
                  </Button>
                )}
                {buyerActions && (
                  <>
                    <Button
                      variant="default"
                      className="bg-success text-success-foreground hover:bg-success/90"
                      onClick={() => run(() => approveQuote.mutateAsync(quote!.id))}
                      disabled={isViewer || approveQuote.isPending}
                      title={isViewer ? viewerTip : undefined}
                    >
                      <ThumbsUp className="h-4 w-4 mr-2" />
                      {t('requestDetailActions.approveQuote')}
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={() => setRejectOpen(true)}
                      disabled={isViewer}
                      title={isViewer ? viewerTip : undefined}
                    >
                      <ThumbsDown className="h-4 w-4 mr-2" />
                      {t('requestDetailActions.rejectQuote')}
                    </Button>
                  </>
                )}
                {isWon && (
                  <Badge variant="outline" className="bg-success/10 text-success border-success/20 py-1.5 px-3">
                    <ThumbsUp className="h-4 w-4 mr-2" />
                    {t('requestDetailActions.dealAccepted')}
                  </Badge>
                )}
              </CardContent>
            </Card>
          );
        })()}

        {/* Quote Content */}
        {quote ? (
          <Card>
            <CardHeader>
              <div className="flex justify-between items-center">
                <div>
                  <CardTitle>{t('requestDetailActions.quoteTitle', { version: quote.version })}</CardTitle>
                  <CardDescription>{quote.status_name} — {new Date(quote.created_at).toLocaleString()}</CardDescription>
                </div>
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">{t('requestDetailActions.totalInclVat')}</p>
                  <p className="text-2xl font-bold text-primary">{formatCurrency(Number(quote.total_incl_vat))}</p>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50">
                    <TableHead>{t('requestDetailActions.itemCol')}</TableHead>
                    <TableHead>{t('requestDetailActions.supplierCol')}</TableHead>
                    <TableHead className="text-right">{t('requestDetailActions.qtyCol')}</TableHead>
                    {/* Base price + margin are seller cost internals — the backend
                        strips them for buyers, so only show the columns to sellers. */}
                    {isSellerSide && <TableHead className="text-right">{t('requestDetailActions.basePriceCol')}</TableHead>}
                    {isSellerSide && <TableHead className="text-right">{t('requestDetailActions.marginCol')}</TableHead>}
                    <TableHead className="text-right">{t('requestDetailActions.finalPriceCol')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(quote.items ?? []).map(item => (
                    <TableRow key={item.id}>
                      <TableCell>
                        <span className="font-medium">{item.product_name || item.imported_raw_name}</span>
                        {item.product_sku && <span className="block text-xs font-mono text-primary">{item.product_sku}</span>}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{item.offer_supplier_name || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{item.quantity}</TableCell>
                      {isSellerSide && <TableCell className="text-right tabular-nums">{formatCurrency(Number(item.frozen_base_price))}</TableCell>}
                      {isSellerSide && (
                        <TableCell className="text-right tabular-nums">
                          {item.margin_percent ? `${Number(item.margin_percent).toFixed(1)}%` : '0%'}
                        </TableCell>
                      )}
                      <TableCell className="text-right tabular-nums font-medium text-primary">
                        {formatCurrency(Number(item.final_price_excl_vat))}
                      </TableCell>
                    </TableRow>
                  ))}
                  {(quote.items?.length ?? 0) === 0 && (
                    <TableRow>
                      <TableCell colSpan={isSellerSide ? 6 : 4} className="text-center py-6 text-muted-foreground">
                        {t('requestDetailActions.noItems')}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-12 flex flex-col items-center justify-center text-muted-foreground">
              <Calculator className="h-10 w-10 mb-2 opacity-20" />
              <p>{t('requestDetailActions.noQuote')}</p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Chat Panel */}
      <div className="flex-[3] min-w-72 max-w-sm sticky top-0 self-start">
        <DealChatPanel dealId={deal.id} />
      </div>

      <RejectQuoteDialog
        quoteId={quote?.id ?? null}
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onConfirm={async (reason) => { if (quote) await run(() => rejectQuote.mutateAsync({ id: quote.id, reason })); }}
      />
    </div>
  );
}

export default RequestDetailPage;
