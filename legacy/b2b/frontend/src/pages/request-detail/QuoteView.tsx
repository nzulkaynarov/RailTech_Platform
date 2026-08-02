import { useState, Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AlertTriangle, Download, Loader2 } from 'lucide-react';
import type { Deal, Quote, QuoteDiffFinding } from '@/api/crmApi';
import { formatDate, formatDateTime } from '@/lib/formatLocale';
import { crmApi } from '@/api/crmApi';
import { quoteStatusLabelKey } from '@/lib/codes';
import { useCurrencyStore } from '@/store/currencyStore';
import { useQuoteRequestDiff } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { CoverageCheck } from '@/components/CRM/CoverageCheck';

/**
 * The priced КП card shown once a quote is visible to the viewer (seller always; buyer only
 * after the КП is actually SENT). Sellers additionally see cost internals (base price, per-line
 * margin) — the backend strips those for buyers, so the columns are seller-gated here too.
 */
export function QuoteView({
  deal,
  quote,
  isSellerSide,
  isBuyerSide,
}: {
  deal: Deal;
  quote: Quote;
  isSellerSide: boolean;
  isBuyerSide: boolean;
}) {
  const { t } = useTranslation();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  // AI #3 «КП vs заявка» coverage/diff state (buyer, received-КП only). Advisory — never gates.
  const [diffFindings, setDiffFindings] = useState<QuoteDiffFinding[]>([]);
  const [diffAiEnabled, setDiffAiEnabled] = useState(true);
  const [diffRan, setDiffRan] = useState(false);
  const quoteDiff = useQuoteRequestDiff();

  // Buyer-facing КП PDF export — same endpoint/wrapper the seller uses. Needed for procurement
  // compliance (tender dossier, archival, forwarding).
  const handleDownloadPdf = async () => {
    setDownloadingPdf(true);
    try {
      await crmApi.exportDealPDF(deal.id);
    } catch (e) {
      toast.error(translateApiError(e));
    } finally {
      setDownloadingPdf(false);
    }
  };

  // AI #3 — compare the received КП against the original request lines. Advisory: the
  // deterministic coverage facts come back even when AI is off (degraded mode).
  const handleQuoteDiffCheck = () => {
    quoteDiff.mutate(quote.id, {
      onSuccess: (data) => {
        setDiffFindings(data.findings);
        setDiffAiEnabled(data.ai_enabled);
        setDiffRan(true);
      },
      onError: (err) => {
        toast.error(translateApiError(err));
      },
    });
  };

  const colCount = isSellerSide ? 7 : 5;
  const validUntilExpired = quote.valid_until
    ? new Date(quote.valid_until) < new Date(new Date().toDateString())
    : false;

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t('requestDetailActions.quoteTitle', { version: quote.version })}</CardTitle>
              <CardDescription>{quoteStatusLabelKey(quote.status_code) ? t(quoteStatusLabelKey(quote.status_code)) : quote.status_name} — {formatDateTime(quote.created_at)}</CardDescription>
              {/* Offer validity — the acceptance deadline. Warn when past. */}
              {quote.valid_until && (
                <p className="flex items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground">{t('requestDetailActions.validUntil')}:</span>
                  <span className={validUntilExpired ? 'font-medium text-destructive' : 'text-foreground'}>
                    {formatDate(quote.valid_until)}
                  </span>
                  {validUntilExpired && (
                    <Badge variant="destructive" className="gap-1">
                      <AlertTriangle className="size-3" aria-hidden="true" />
                      {t('requestDetailActions.validUntilExpired')}
                    </Badge>
                  )}
                </p>
              )}
            </div>
            <div className="flex items-start gap-4">
              <div className="text-right">
                <p className="text-sm text-muted-foreground">{t('requestDetailActions.totalInclVat')}</p>
                <p className="text-2xl font-bold text-primary">{formatCurrency(Number(quote.total_incl_vat))}</p>
              </div>
              {/* PDF export — buyer parity with seller. */}
              <Button variant="outline" size="sm" className="shrink-0 gap-1.5" onClick={handleDownloadPdf} disabled={downloadingPdf}>
                {downloadingPdf ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                {t('requestDetailActions.downloadPdf')}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Seller's cover comment / conditions on the КП. */}
          {(quote.notes ?? '').trim() && (
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <p className="mb-1 text-xs font-medium text-muted-foreground">{t('requestDetailActions.sellerNote')}</p>
              <p className="whitespace-pre-line text-sm">{quote.notes}</p>
            </div>
          )}
          <div className="overflow-x-auto">
          <Table className="min-w-[32rem]">
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead>{t('requestDetailActions.itemCol')}</TableHead>
                <TableHead className="w-20">{t('requestItems.unitCol')}</TableHead>
                <TableHead>{t('requestDetailActions.supplierCol')}</TableHead>
                <TableHead className="text-right">{t('requestDetailActions.qtyCol')}</TableHead>
                {/* Base price + margin are seller cost internals — the backend strips them for
                    buyers, so only show the columns to sellers. */}
                {isSellerSide && <TableHead className="text-right">{t('requestDetailActions.basePriceCol')}</TableHead>}
                {isSellerSide && <TableHead className="text-right">{t('requestDetailActions.marginCol')}</TableHead>}
                <TableHead className="text-right">{t('requestDetailActions.finalPriceCol')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(quote.items ?? []).map(item => (
                <Fragment key={item.id}>
                <TableRow className={item.note ? 'border-0' : ''}>
                  <TableCell>
                    <span className="font-medium">{item.product_name || item.imported_raw_name}</span>
                    {/* Buyer's own identifiers travel with the line — these are in the DB and
                        not seller-only, so surface them. */}
                    <span className="block space-x-2 text-xs font-mono text-muted-foreground">
                      {item.product_sku && <span className="text-primary">{item.product_sku}</span>}
                      {(item.mpn || item.product_mpn) && <span>{t('requestItems.skuLabel')}: {item.mpn || item.product_mpn}</span>}
                      {(item.gost_drawing || item.product_gost) && <span>{t('requestItems.gostLabel')}: {item.gost_drawing || item.product_gost}</span>}
                    </span>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{item.unit || item.product_uom || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{item.offer_supplier_name || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{item.quantity}</TableCell>
                  {isSellerSide && <TableCell className="text-right tabular-nums">{formatCurrency(Number(item.frozen_base_price))}</TableCell>}
                  {isSellerSide && (
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {/* Per-line margin_percent (DT1): NULL — «наследовать маржу КП» (muted «—»);
                          any non-null value is an explicit override, INCLUDING 0 = «продать по
                          себестоимости» → «0.0%». Never conflate inherit with 0 (mirrors the КП grid). */}
                      {item.margin_percent == null
                        ? '—'
                        : `${Number(item.margin_percent).toFixed(1)}%`}
                    </TableCell>
                  )}
                  <TableCell className="text-right tabular-nums font-medium text-primary">
                    {formatCurrency(Number(item.final_price_excl_vat))}
                  </TableCell>
                </TableRow>
                {item.note && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={colCount} className="pt-0 text-xs text-muted-foreground">
                      <span className="font-medium">{t('requestItems.noteCol')}:</span> <span className="whitespace-pre-line">{item.note}</span>
                    </TableCell>
                  </TableRow>
                )}
                </Fragment>
              ))}
              {(quote.items?.length ?? 0) === 0 && (
                <TableRow>
                  <TableCell colSpan={colCount} className="text-center py-6 text-muted-foreground">
                    {t('requestDetailActions.noItems')}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          </div>
          {/* VAT breakdown — the canonical Subtotal → VAT → Total bridge, so the buyer isn't
              left to reconcile excl-VAT lines with an incl-VAT grand total by hand. */}
          <div className="ml-auto w-full max-w-xs space-y-1 text-sm">
            <div className="flex justify-between text-muted-foreground">
              <span>{t('requestDetailActions.subtotal')}</span>
              <span className="tabular-nums">{formatCurrency(Number(quote.subtotal_excl_vat))}</span>
            </div>
            {/* Charges/allowances line — without it Subtotal + VAT ≠ Total and the buyer sees an
                unexplained number (audit M11). Shown whenever the КП carries any charge so the
                money bridge always reconciles. */}
            {quote.charges_total != null && Number(quote.charges_total) !== 0 && (
              <div className="flex justify-between text-muted-foreground">
                <span>{t('requestDetailActions.charges')}</span>
                <span className="tabular-nums">{formatCurrency(Number(quote.charges_total))}</span>
              </div>
            )}
            <div className="flex justify-between text-muted-foreground">
              <span>{t('requestDetailActions.vatAmount')}{quote.vat_rate ? ` (${Number(quote.vat_rate).toFixed(0)}%)` : ''}</span>
              <span className="tabular-nums">{formatCurrency(Number(quote.vat_amount))}</span>
            </div>
            <div className="flex justify-between border-t border-border pt-1 font-semibold">
              <span>{t('requestDetailActions.totalInclVat')}</span>
              <span className="tabular-nums text-primary">{formatCurrency(Number(quote.total_incl_vat))}</span>
            </div>
          </div>
        </CardContent>
      </Card>
      {/* AI #3 — «КП vs заявка» coverage / discrepancy check. Buyer-only and only once the КП has
          actually been sent back; purely advisory. */}
      {isBuyerSide && (quote.items?.length ?? 0) > 0 && (
        <CoverageCheck
          items={quote.items ?? []}
          findings={diffFindings}
          aiEnabled={diffAiEnabled}
          isPending={quoteDiff.isPending}
          hasRun={diffRan}
          onCheck={handleQuoteDiffCheck}
        />
      )}
    </>
  );
}

export default QuoteView;
