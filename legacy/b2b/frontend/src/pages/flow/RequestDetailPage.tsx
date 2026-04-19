import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useFlowStore } from '@/store/flowStore';
import { ArrowLeft, Send, Calculator, ThumbsUp, ThumbsDown, User, Briefcase } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { LoadingSkeleton } from '@/components/LoadingSkeleton';
import { DealChatPanel } from '@/components/Sourcing/DealChatPanel';
import { useCurrencyStore } from '@/store/currencyStore';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { RejectQuoteDialog } from '@/components/CRM/RejectQuoteDialog';

export function RequestDetailPage({ onBack }: { onBack: () => void; onNavigate: (t: string) => void }) {
  const { t } = useTranslation();
  const { activeDealId, deal, quote, loadDeal, loading, changeDealStage, approveQuote, rejectQuote, sendQuoteToClient } = useFlowStore();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [rejectOpen, setRejectOpen] = useState(false);
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');

  useEffect(() => {
    if (activeDealId) {
      loadDeal(activeDealId);
    }
  }, [activeDealId, loadDeal]);

  if (loading && !deal) return <LoadingSkeleton />;
  if (!deal) return <div className="p-8 text-center text-muted-foreground">{t('pages.common.noData')}</div>;

  const isDraft = deal.stage_code === 'DRAFT';
  const isSourcing = deal.stage_code === 'SOURCING';
  const isCalculating = deal.stage_code === 'CALCULATING';
  const isQuoteSent = deal.stage_code === 'QUOTE_SENT';
  const isWon = deal.stage_code === 'CLOSED_WON' || deal.stage_code === 'CONTRACT_SIGNED';

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

        {/* Action Bar */}
        <Card className="bg-muted/30">
          <CardContent className="flex items-center gap-3 py-4">
            <span className="text-sm font-medium">{t('requestDetailActions.actionsLabel')}:</span>
            {isDraft && (
              <Button
                variant="default"
                onClick={() => changeDealStage(deal.id, 'SOURCING')}
                disabled={isViewer}
                title={isViewer ? viewerTip : undefined}
              >
                {t('requestDetailActions.startSourcing')}
              </Button>
            )}
            {isSourcing && (
              <Button
                variant="default"
                onClick={() => changeDealStage(deal.id, 'CALCULATING')}
                disabled={isViewer}
                title={isViewer ? viewerTip : undefined}
              >
                <Calculator className="h-4 w-4 mr-2" />
                {t('requestDetailActions.startCalculation')}
              </Button>
            )}
            {isCalculating && quote && (
              <Button
                variant="default"
                onClick={() => sendQuoteToClient(quote.id)}
                disabled={isViewer}
                title={isViewer ? viewerTip : undefined}
              >
                <Send className="h-4 w-4 mr-2" />
                {t('requestDetailActions.sendQuote')}
              </Button>
            )}
            {isQuoteSent && quote && (
              <>
                <Button
                  variant="default"
                  className="bg-success text-success-foreground hover:bg-success/90"
                  onClick={() => approveQuote(quote.id)}
                  disabled={isViewer}
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
            {!isDraft && !isSourcing && !isCalculating && !isQuoteSent && !isWon && (
              <span className="text-sm text-muted-foreground">{t('requestDetailActions.noActions')}</span>
            )}
          </CardContent>
        </Card>

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
                    <TableHead className="text-right">{t('requestDetailActions.basePriceCol')}</TableHead>
                    <TableHead className="text-right">{t('requestDetailActions.marginCol')}</TableHead>
                    <TableHead className="text-right">{t('requestDetailActions.finalPriceCol')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {quote.items.map(item => (
                    <TableRow key={item.id}>
                      <TableCell>
                        <span className="font-medium">{item.product_name || item.imported_raw_name}</span>
                        {item.product_sku && <span className="block text-xs font-mono text-primary">{item.product_sku}</span>}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{item.offer_supplier_name || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{item.quantity}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatCurrency(Number(item.frozen_base_price))}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {item.margin_percent ? `${Number(item.margin_percent).toFixed(1)}%` : '0%'}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium text-primary">
                        {formatCurrency(Number(item.final_price_excl_vat))}
                      </TableCell>
                    </TableRow>
                  ))}
                  {quote.items.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center py-6 text-muted-foreground">
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
        <DealChatPanel />
      </div>

      {/* HIGH-10: ask user for a reason instead of a hardcoded EN string */}
      <RejectQuoteDialog
        quoteId={quote?.id ?? null}
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onConfirm={async (reason) => { if (quote) await rejectQuote(quote.id, reason); }}
      />
    </div>
  );
}
