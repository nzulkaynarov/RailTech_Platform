import { useState, Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Send, Calculator, ThumbsUp, ThumbsDown, User, Briefcase, Download, Loader2, AlertTriangle, FileText, Handshake } from 'lucide-react';
import { toast } from 'sonner';
import { QuoteStatus, DealStage, DEAL_STAGE_LABEL_KEY, quoteStatusLabelKey } from '@/lib/codes';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { useDeal, useChangeDealStage, useApproveQuote, useRejectQuote, useSendQuoteToClient, useUpdateRequestMeta, usePreflightCheck, useQuoteRequestDiff, useClaimDeal } from '@/hooks/useCRM';
import { crmApi } from '@/api/crmApi';
import type { PreflightFinding, PreflightLine, QuoteDiffFinding } from '@/api/crmApi';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { LoadingSkeleton } from '@/components/LoadingSkeleton';
import { DealChatPanel } from '@/components/Sourcing/DealChatPanel';
import { RejectQuoteDialog } from '@/components/CRM/RejectQuoteDialog';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { RequestItemsEditor } from '@/components/CRM/RequestItemsEditor';
import { PreflightWarnings } from '@/components/CRM/PreflightWarnings';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { CoverageCheck } from '@/components/CRM/CoverageCheck';
import { DealTimeline } from '@/components/CRM/DealTimeline';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { buyerStatus } from '@/lib/requestStatus';

/**
 * Canonical buyer-facing deal/КП detail surface. Reached via the
 * `request-detail/<dealId>` hash route (My Requests / Sourcing / cart / import).
 * State is React Query throughout (useDeal + useCRM) — the old Zustand
 * `flowStore` flow was retired. Seller-side stage actions remain for sellers who
 * land here from the sourcing list; the buyer only ever sees approve/reject.
 */
export function RequestDetailPage({ dealId, onBack }: { dealId: number; onBack: () => void }) {
  const { t } = useTranslation();
  const { data: deal, isLoading, isError, refetch } = useDeal(dealId);
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [approveConfirmOpen, setApproveConfirmOpen] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [generateQuoteOpen, setGenerateQuoteOpen] = useState(false);
  // AI #7 pre-flight advisory state (DRAFT buyer request only). Findings are
  // purely advisory — they never gate submitting the RFQ.
  const [preflightFindings, setPreflightFindings] = useState<PreflightFinding[]>([]);
  const [preflightRan, setPreflightRan] = useState(false);
  const preflightCheck = usePreflightCheck();
  // AI #3 «КП vs заявка» coverage/diff state (buyer, received-КП only). Advisory —
  // never gates approve/reject.
  const [diffFindings, setDiffFindings] = useState<QuoteDiffFinding[]>([]);
  const [diffAiEnabled, setDiffAiEnabled] = useState(true);
  const [diffRan, setDiffRan] = useState(false);
  const quoteDiff = useQuoteRequestDiff();
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');

  const changeStage = useChangeDealStage();
  const approveQuote = useApproveQuote();
  const rejectQuote = useRejectQuote();
  const sendQuote = useSendQuoteToClient();
  const updateMeta = useUpdateRequestMeta();
  const claimMut = useClaimDeal();

  // Gate seller-side actions (start sourcing / calculation / send quote) to
  // sellers. A buyer would only hit backend guards — and the buttons are
  // meaningless on their screen.
  const activeStatus = useUserStore((s) => s.activeStatus);
  const isSellerSide = activeStatus === 'SELLER';
  const isBuyerSide = activeStatus === 'BUYER';

  if (isLoading && !deal) return <LoadingSkeleton />;
  // A failed fetch (404 / no-access / network / Neon sleep) must read as an
  // error with a way out — not a bare "no data" that looks like an empty deal.
  if (isError && !deal) return (
    <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
        <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium">{t('common.loadError')}</p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => refetch()}>{t('common.retry')}</Button>
        <Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft className="mr-1.5 h-4 w-4" />{t('requestDetailActions.backToRequests')}</Button>
      </div>
    </div>
  );
  if (!deal) return <div className="p-8 text-center text-muted-foreground">{t('pages.common.noData')}</div>;

  const quote = deal.active_quote ?? deal.quotes?.[deal.quotes.length - 1] ?? null;

  const isDraft = deal.stage_code === DealStage.DRAFT;
  const isSourcing = deal.stage_code === DealStage.SOURCING;
  const isCalculating = deal.stage_code === DealStage.CALCULATING;
  const isQuoteSent = deal.stage_code === DealStage.QUOTE_SENT;
  const isWon = deal.stage_code === DealStage.CLOSED_WON || deal.stage_code === DealStage.CONTRACT_SIGNED;
  // Seller КП-builder entry (consolidated here from the old Deals side-sheet):
  // create the КП once the deal is in work, or open the focused builder if it exists.
  const canBuildQuote = isSellerSide && (isSourcing || isCalculating) && !deal.active_quote;
  const hasQuote = isSellerSide && !!deal.active_quote;
  // Buyer rejected the КП → the seller was stuck (no build button while an
  // active_quote exists). Offer a primary "new version" action: perform_create
  // auto-increments version, so this simply starts v2 of the КП.
  const canBuildNewVersion = isSellerSide && deal.active_quote?.status_code === QuoteStatus.REJECTED;
  // Third in-funnel path to «взять в работу» (Kanban + deals list are the others).
  // Seller-only pull from the routed queue; `assigned_to` (the id, derived from the
  // viewer's OWN routing row) == null means this seller's copy is unclaimed. Reuses
  // useClaimDeal + the `dealsKanban.claim`/`.claimed` keys.
  const canClaim = isSellerSide && deal.assigned_to == null;
  const openQuoteBuilder = () => { window.location.hash = `deal-quote/${deal.id}`; };
  // Buyer may build/edit their own request (name + qty) until the seller engages.
  // The backend is the source of truth (can_edit_request); the UI only reflects it.
  const canEditRequest = !!deal.can_edit_request;
  // A request has NO price — the client never sets one. Prices belong to the
  // seller's КП and are shown to the buyer ONLY after the КП is actually sent
  // back (SENT / APPROVED / REJECTED). The seller side always sees pricing.
  const quoteSentToBuyer = [QuoteStatus.SENT, QuoteStatus.APPROVED, QuoteStatus.REJECTED].includes(
    (quote?.status_code ?? '') as never,
  );
  const showPricedQuote = !!quote && (isSellerSide || quoteSentToBuyer);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  // Buyer-facing КП PDF export — same endpoint/wrapper the seller uses. Needed
  // for procurement compliance (tender dossier, archival, forwarding).
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

  // Map the buyer's draft request lines → the advisory pre-flight check payload.
  // Only the buyer-owned fields travel (no price); the backend validates indices.
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

  // AI #3 — compare the received КП against the original request lines. Advisory:
  // the deterministic coverage facts come back even when AI is off (degraded mode).
  const handleQuoteDiffCheck = () => {
    if (!quote) return;
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

  return (
    <div className="flex gap-4 w-full min-w-0">
      <div className="flex flex-col gap-3 flex-[7] min-w-0">

        {/* Header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack}><ArrowLeft className="h-4 w-4" /></Button>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              {canEditRequest ? (
                <div className="flex max-w-md flex-1 items-center gap-2">
                  <Input
                    defaultValue={deal.title || ''}
                    onBlur={(e) => {
                      const value = e.target.value.trim();
                      // Empty title is not a valid edit — restore the previous
                      // value in the field instead of silently keeping the old
                      // DB value while the input looks blank.
                      if (!value) { e.target.value = deal.title || ''; return; }
                      if (value !== (deal.title || '')) {
                        updateMeta.mutate({ dealId: deal.id, title: value }, {
                          onError: (err) => { e.target.value = deal.title || ''; toast.error(translateApiError(err)); },
                        });
                      }
                    }}
                    className="h-auto border-transparent bg-transparent px-1 text-2xl font-bold hover:border-input focus-visible:border-input"
                    aria-label={t('requestDetailActions.titleLabel')}
                  />
                  {updateMeta.isPending && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden="true" />}
                </div>
              ) : (
                <h1 className="text-2xl font-bold">{deal.title || `#${deal.id}`}</h1>
              )}
              {isBuyerSide ? (
                <StatusBadge label={t(buyerStatus(deal.stage_code).labelKey)} variant={buyerStatus(deal.stage_code).variant} />
              ) : (
                <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20">
                  {deal.stage_code && DEAL_STAGE_LABEL_KEY[deal.stage_code]
                    ? t(DEAL_STAGE_LABEL_KEY[deal.stage_code])
                    : deal.stage_name}
                </Badge>
              )}
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
            {/* Multi-seller routing — the seller companies this RFQ is routed to. */}
            {(deal.target_sellers_data?.length ?? 0) > 0 && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">{t('requestDetailActions.routedTo')}:</span>
                {deal.target_sellers_data!.map((seller) => (
                  <Badge key={seller.id} variant="secondary">{seller.name}</Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Action Bar. Seller-side actions (start sourcing / start calculation
            / send quote) only show for SELLER / MANUFACTURER. Buyer only sees
            approve / reject once the quote is sent. */}
        {(() => {
          const sellerActions = isSellerSide && (isDraft || isSourcing || isCalculating || hasQuote || canBuildNewVersion);
          const buyerActions = isBuyerSide && isQuoteSent && quote;
          const showActionBar = sellerActions || buyerActions || isWon || canClaim;
          if (!showActionBar) {
            // A buyer editing a draft already gets this guidance from the "Your
            // request" card subtitle — don't waste a whole banner repeating it.
            if (isBuyerSide && canEditRequest) return null;
            return (
              <p className="text-sm text-muted-foreground">
                {isBuyerSide ? t('requestDetailActions.buyerWaitHint') : t('requestDetailActions.noActions')}
              </p>
            );
          }
          return (
            <Card className="bg-muted/30">
              <CardContent className="flex items-center gap-3 py-4">
                <span className="text-sm font-medium">{t('requestDetailActions.actionsLabel')}:</span>
                {canClaim && (
                  <Button
                    variant="outline"
                    onClick={() => claimMut.mutate(deal.id, {
                      onSuccess: () => toast.success(t('dealsKanban.claimed')),
                      onError: (err) => toast.error(translateApiError(err)),
                    })}
                    disabled={isViewer || claimMut.isPending}
                    title={isViewer ? viewerTip : undefined}
                  >
                    {claimMut.isPending
                      ? <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
                      : <Handshake className="h-4 w-4 mr-2" aria-hidden="true" />}
                    {t('dealsKanban.claim')}
                  </Button>
                )}
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
                {/* КП builder entry — create it, then open the focused full-page
                    builder (QuoteBuilderGrid: pricing, basis, charges, approval chain). */}
                {canBuildQuote && (
                  <Button
                    variant="default"
                    onClick={() => setGenerateQuoteOpen(true)}
                    disabled={isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <FileText className="h-4 w-4 mr-2" />
                    {t('generateQuote.submit')}
                  </Button>
                )}
                {/* КП rejected by the buyer — primary path out of the тупик:
                    start a fresh version (backend auto-increments), then open
                    the builder for it (GenerateQuoteDialog.onGenerated). */}
                {canBuildNewVersion && (
                  <Button
                    variant="default"
                    onClick={() => setGenerateQuoteOpen(true)}
                    disabled={isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <FileText className="h-4 w-4 mr-2" />
                    {t('requestDetailActions.newQuoteVersion')}
                  </Button>
                )}
                {hasQuote && (
                  <Button variant="outline" onClick={openQuoteBuilder}>
                    <FileText className="h-4 w-4 mr-2" />
                    {t('pages.deals.detail.openQuote')}
                  </Button>
                )}
                {/* Only an internally-approved КП can be sent (backend requires
                    READY_TO_SEND). Getting there is done via the approval chain on
                    the Deals page; this stays disabled until then. */}
                {isSellerSide && quote?.status_code === QuoteStatus.READY_TO_SEND && (
                  <Button
                    variant="default"
                    onClick={() => run(() => sendQuote.mutateAsync({ id: quote.id }))}
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
                      onClick={() => setApproveConfirmOpen(true)}
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
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant="outline" className="bg-success/10 text-success border-success/20 py-1.5 px-3">
                      <ThumbsUp className="h-4 w-4 mr-2" />
                      {t('requestDetailActions.dealAccepted')}
                    </Badge>
                    {/* The approval auto-materializes the Contract (B1) — carry the buyer straight
                        to it instead of a terminal badge with no next step (audit B2). */}
                    <Button size="sm" onClick={() => { window.location.hash = 'contracts'; }}>
                      <FileText className="h-4 w-4 mr-2" />
                      {t('requestDetailActions.openContract')}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })()}

        {/* Note to the seller — the buyer's free-text request description. Editable
            while drafting, read-only (and visible to the seller) afterwards. */}
        {(canEditRequest || (deal.notes ?? '').trim()) && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t('requestDetailActions.noteToSeller')}</CardTitle>
            </CardHeader>
            <CardContent>
              {canEditRequest ? (
                <Textarea
                  defaultValue={deal.notes ?? ''}
                  onBlur={(e) => { if (e.target.value !== (deal.notes ?? '')) updateMeta.mutate({ dealId: deal.id, notes: e.target.value }); }}
                  placeholder={t('requestDetailActions.noteToSellerPlaceholder')}
                  rows={2}
                />
              ) : (
                <p className="whitespace-pre-line text-sm text-muted-foreground">{deal.notes}</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* What the buyer sees about their request:
            1. canEditRequest      → editable items (name + qty, no price)
            2. КП sent back / seller → the priced quote table
            3. seller pricing, not sent yet → request items READ-ONLY, no price
               (never leak an in-progress price or a confusing "$0" to the buyer)
            4. nothing yet         → empty state */}
        {canEditRequest ? (
          <>
            <RequestItemsEditor
              dealId={deal.id}
              items={quote?.items ?? []}
              canEdit
              hasRecipients={(deal.target_sellers_data?.length ?? 0) > 0}
            />
            {/* AI #7 advisory pre-flight quality check — buyer reviews warnings
                before submitting; never blocks. Only shown when there are lines. */}
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
        ) : showPricedQuote ? (
          (() => {
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
                  <CardDescription>{quoteStatusLabelKey(quote.status_code) ? t(quoteStatusLabelKey(quote.status_code)) : quote.status_name} — {new Date(quote.created_at).toLocaleString()}</CardDescription>
                  {/* Offer validity — the acceptance deadline. Warn when past. */}
                  {quote.valid_until && (
                    <p className="flex items-center gap-1.5 text-xs">
                      <span className="text-muted-foreground">{t('requestDetailActions.validUntil')}:</span>
                      <span className={validUntilExpired ? 'font-medium text-destructive' : 'text-foreground'}>
                        {new Date(quote.valid_until).toLocaleDateString()}
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
                    {/* Base price + margin are seller cost internals — the backend
                        strips them for buyers, so only show the columns to sellers. */}
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
                        {/* Buyer's own identifiers travel with the line — these
                            are in the DB and not seller-only, so surface them. */}
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
                          {/* Per-line margin_percent is a dead placeholder (model default 0) — the КП
                              markup is applied at quote level, so this endpoint never carries a real
                              per-line value. Show «—» instead of a misleading «0.0%» (WP-7). */}
                          {item.margin_percent != null && Number(item.margin_percent) !== 0
                            ? `${Number(item.margin_percent).toFixed(1)}%`
                            : '—'}
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
              {/* VAT breakdown — the canonical Subtotal → VAT → Total bridge,
                  so the buyer isn't left to reconcile excl-VAT lines with an
                  incl-VAT grand total by hand. */}
              <div className="ml-auto w-full max-w-xs space-y-1 text-sm">
                <div className="flex justify-between text-muted-foreground">
                  <span>{t('requestDetailActions.subtotal')}</span>
                  <span className="tabular-nums">{formatCurrency(Number(quote.subtotal_excl_vat))}</span>
                </div>
                {/* Charges/allowances line — without it Subtotal + VAT ≠ Total and the buyer
                    sees an unexplained number (audit M11). Shown whenever the КП carries any
                    charge so the money bridge always reconciles. */}
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
          {/* AI #3 — «КП vs заявка» coverage / discrepancy check. Buyer-only and
              only once the КП has actually been sent back; purely advisory. */}
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
          })()
        ) : quote && (quote.items?.length ?? 0) > 0 ? (
          // Seller is working the КП but hasn't sent it — buyer sees their
          // requested items read-only, WITHOUT any price.
          <RequestItemsEditor dealId={deal.id} items={quote.items ?? []} canEdit={false} />
        ) : (
          <Card>
            <CardContent className="py-12 flex flex-col items-center justify-center text-muted-foreground">
              <Calculator className="h-10 w-10 mb-2 opacity-20" />
              <p>{t('requestDetailActions.noQuote')}</p>
            </CardContent>
          </Card>
        )}

        {/* CRM Phase A — deal history feed (renders nothing while empty) */}
        <DealTimeline dealId={deal.id} />
      </div>

      {/* Chat Panel — pass routed sellers so the buyer picks a private lane per seller (audit #4) */}
      <div className="w-80 shrink-0 sticky top-0 self-start hidden lg:flex flex-col">
        <DealChatPanel dealId={deal.id} sellers={deal.target_sellers_data} />
      </div>

      <RejectQuoteDialog
        quoteId={quote?.id ?? null}
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onConfirm={async (reason) => { if (quote) await run(() => rejectQuote.mutateAsync({ id: quote.id, reason })); }}
      />

      {/* Approving commits the deal to a contract — confirm before the
          irreversible accept (parity with the reject dialog). */}
      <ConfirmActionDialog
        open={approveConfirmOpen}
        onOpenChange={setApproveConfirmOpen}
        title={t('confirmActions.approveQuote.title')}
        description={t('confirmActions.approveQuote.description')}
        variant="primary"
        confirmLabel={t('requestDetailActions.approveQuote')}
        onConfirm={async () => { if (quote) await approveQuote.mutateAsync(quote.id); }}
        translateError={(code) => translateApiError(code)}
      />

      {/* Seller: create the КП, then jump straight into the focused builder. */}
      <GenerateQuoteDialog
        dealId={deal.id}
        open={generateQuoteOpen}
        onOpenChange={setGenerateQuoteOpen}
        onGenerated={openQuoteBuilder}
      />
    </div>
  );
}

export default RequestDetailPage;
