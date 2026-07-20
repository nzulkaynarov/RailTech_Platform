import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Calculator, FileText, Send, FileSignature, AlertTriangle, MessageSquare, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { StatusBadge, getDealStageVariant } from '@/components/ui/StatusBadge';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useDeal, useSendQuoteToClient } from '@/hooks/useCRM';
import { useQuoteSendGate } from '@/hooks/useQuoteSendGate';
import { translateApiError, extractApiErrorCode } from '@/lib/apiError';
import { QuoteBuilderGrid } from '@/components/Admin/QuoteBuilderGrid';
import { QuoteApprovalChain } from '@/components/CRM/QuoteApprovalChain';
import { QuoteSendGateBanner } from '@/components/CRM/QuoteSendGateBanner';
import { DealChatPanel } from '@/components/Sourcing/DealChatPanel';
import { GenerateContractDialog } from '@/components/CRM/GenerateContractDialog';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { QuoteStatus, DEAL_STAGE_LABEL_KEY } from '@/lib/codes';
import { LoadingRows, EmptyState } from './shared/PageShell';

interface DealQuotePageProps {
  dealId: number;
  onBack: () => void;
  /** App-level hash navigation, for the send-gate banner CTA (KYC / subscription). */
  onNavigate?: (target: string) => void;
}

/**
 * Full-page seller КП (quote) builder. Replaces the cramped in-sheet builder:
 * the wide line-item/price grid + approval chain need the whole viewport, not a
 * side panel. Reached via the `deal-quote/<dealId>` hash route from DealsPage.
 * State is React Query throughout (useDeal / useCRM) — no flowStore.
 */
export function DealQuotePage({ dealId, onBack, onNavigate }: DealQuotePageProps) {
  const { t } = useTranslation();
  const { data: deal, isLoading, isError, refetch } = useDeal(dealId);
  const sendQuote = useSendQuoteToClient();
  // WP-H: proactive KYC/entitlement send-gate — banner up-front + disabled Send with the reason.
  const sendGate = useQuoteSendGate();
  const [contractOpen, setContractOpen] = useState(false);
  const [sendConfirmOpen, setSendConfirmOpen] = useState(false);
  // S7a: the backend demanded a below-floor justification for a sender WITHOUT cost visibility
  // (who never saw below_floor). Flip to true reactively so the confirm dialog re-prompts.
  const [justificationRequired, setJustificationRequired] = useState(false);
  // Single Deal-workspace (#3b): the buyer's request context lives ON the builder
  // screen, so a seller prices the КП without bouncing back to the deal page. The
  // ask (deal.notes) collapses to one line by default; the full thread opens in a slide-over.
  const [chatOpen, setChatOpen] = useState(false);
  const [noteExpanded, setNoteExpanded] = useState(false);
  // WP-D navigation guard: the builder reports unsaved line edits up here so leaving the
  // workspace (the Back button) prompts a confirm instead of silently dropping the changes.
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false);

  const handleBack = () => {
    if (hasUnsavedChanges) {
      setLeaveConfirmOpen(true);
      return;
    }
    onBack();
  };

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6 p-6">
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

  // S7a: below the margin floor a written justification is required to send. Two cost-visibility
  // cases: (a) sender WITH cost/margin rights sees economics.below_floor → prompt proactively;
  // (b) sender WITHOUT rights has economics === null → prompt reactively once the backend returns
  // BELOW_FLOOR_JUSTIFICATION_REQUIRED. The reason textarea is shown/required in either case.
  const belowFloorVisible = !!quote?.economics?.below_floor;
  const needJustification = justificationRequired || belowFloorVisible;

  // Sending the КП is irreversible and client-visible (the buyer immediately
  // sees the priced offer + frozen prices) → gate behind a confirm dialog.
  const confirmSend = async ({ reason }: { reason: string }) => {
    if (!quote) return;
    try {
      // Errors (e.g. QUOTE_SEND_NOT_ENTITLED) propagate to the ConfirmActionDialog's translateError,
      // which renders the friendly apiErrors.* message — don't swallow them here.
      await sendQuote.mutateAsync({ id: quote.id, justification: reason || undefined });
      toast.success(t('pages.deals.detail.quoteSentToast'));
      setJustificationRequired(false);
    } catch (err) {
      // Reactive path (b): the sender couldn't see below_floor — surface the justification field
      // and let them retry with text. Re-throw so the dialog shows the translated toast + stays open.
      if (extractApiErrorCode(err) === 'BELOW_FLOOR_JUSTIFICATION_REQUIRED') {
        setJustificationRequired(true);
      }
      throw err;
    }
  };

  const hasNote = (deal.notes ?? '').trim().length > 0;

  return (
    <div className="flex h-full flex-col">
      {/* Single workspace toolbar (~48px): back + compact context + approval pill (left),
          seller lifecycle actions (right). Replaces the old two-storey page header. */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b px-4 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Button variant="ghost" size="icon" className="size-8 shrink-0" onClick={handleBack} aria-label={t('common.back')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <FileText className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <h1 className="min-w-0 truncate text-sm font-semibold" title={deal.title || undefined}>
            <span className="text-muted-foreground">{t('pages.dealQuote.title')}</span>
            {' · '}
            {deal.title || `${t('pages.deals.deal')} #${deal.id}`}
            {(deal.client_name || deal.company_name)
              ? <span className="font-normal text-muted-foreground">{` · ${deal.client_name || deal.company_name}`}</span>
              : ''}
          </h1>
          <StatusBadge
            className="shrink-0"
            label={deal.stage_code && DEAL_STAGE_LABEL_KEY[deal.stage_code]
              ? t(DEAL_STAGE_LABEL_KEY[deal.stage_code])
              : (deal.stage_name ?? '')}
            variant={getDealStageVariant(deal.stage_code ?? '')}
          />
          {/* КП internal approval chain (документооборот) — compact pill + Popover. */}
          {quote && <QuoteApprovalChain quote={quote} />}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setChatOpen(true)}>
            <MessageSquare className="mr-2 h-4 w-4" />
            {t('pages.dealQuote.openChat')}
          </Button>
          {canContract && (
            <Button size="sm" variant="outline" onClick={() => setContractOpen(true)}>
              <FileSignature className="mr-2 h-4 w-4" />
              {t('contractGenerateDialog.generate')}
            </Button>
          )}
          {canSend && (
            sendGate.blocked ? (
              // A known blocker (KYC / subscription / demo) → disable Send and explain why via a
              // tooltip, using the SAME apiErrors.* copy the backend would return. A disabled button
              // swallows pointer events, so the wrapping span carries the tooltip trigger.
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span tabIndex={0} className="inline-flex">
                      <Button size="sm" disabled aria-disabled>
                        <Send className="mr-2 h-4 w-4" />
                        {t('requestDetailActions.sendQuote')}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    {translateApiError(sendGate.errorCode ?? '')}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <Button size="sm" disabled={sendQuote.isPending} onClick={() => setSendConfirmOpen(true)}>
                <Send className="mr-2 h-4 w-4" />
                {t('requestDetailActions.sendQuote')}
              </Button>
            )
          )}
        </div>
      </div>

      {/* Buyer's ask — one-line collapsible (single Deal-workspace #3b): collapsed by default
          so it costs ~1 line, expands in place. */}
      {hasNote && (
        <button
          type="button"
          onClick={() => setNoteExpanded((v) => !v)}
          aria-expanded={noteExpanded}
          className="flex w-full items-start gap-2 border-b bg-muted/40 px-4 py-1.5 text-left hover:bg-muted/60"
        >
          <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground shrink-0">
            {t('pages.dealQuote.buyerNote')}:
          </span>
          <span className={cn('min-w-0 flex-1 whitespace-pre-line text-xs text-foreground', noteExpanded ? '' : 'line-clamp-1')}>
            {deal.notes}
          </span>
          <ChevronDown className={cn('mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', noteExpanded && 'rotate-180')} aria-hidden="true" />
        </button>
      )}

      {/* Wave E F3: «калькулятор» draft — no client yet. One compact line so the seller knows
          why the header shows no counterparty and that «Отправить» will ask for a recipient
          (backend answers RECIPIENT_REQUIRED). Shown only while the deal has no client at all. */}
      {!deal.company_name && !deal.client_name && (
        <div className="flex items-start gap-2 border-b bg-muted/40 px-4 py-1.5">
          <Calculator className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground shrink-0">
            {t('pages.dealQuote.calculatorDraft')}:
          </span>
          <span className="min-w-0 flex-1 text-xs text-muted-foreground">
            {t('pages.dealQuote.calculatorDraftHint')}
          </span>
        </div>
      )}

      {/* WP-H: proactive send-gate banner — surfaces a KYC/subscription/demo blocker BEFORE the
          seller finishes pricing, instead of a late surprise at «Отправить». Seller-side only.
          U2: dismissible here — folding it away returns its row to the line grid on a 14" screen,
          and the disabled «Отправить» button still explains the blocker at the point of action. */}
      <QuoteSendGateBanner onNavigate={onNavigate} dismissible />

      {/* Builder — fills the remaining viewport height; it owns the single vertical scroll. */}
      {quote ? (
        // U2: `p-2` (was `p-3`) — 8px of the reclaimed chrome goes straight back to visible lines.
        <div className="min-h-0 flex-1 p-2">
          <QuoteBuilderGrid dealId={dealId} onDirtyChange={setHasUnsavedChanges} />
        </div>
      ) : (
        <div className="p-6">
          <EmptyState
            icon={<FileText className="h-5 w-5" />}
            message={t('pages.dealQuote.noQuote')}
            hint={t('pages.dealQuote.noQuoteHint')}
            action={{ label: t('common.back'), onClick: onBack }}
          />
        </div>
      )}

      {/* Buyer thread — slide-over so the seller never leaves the builder to reply. */}
      <Sheet open={chatOpen} onOpenChange={setChatOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
          <SheetHeader className="border-b px-4 py-3">
            <SheetTitle>{t('pages.dealQuote.contextTitle')}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-hidden p-4">
            <DealChatPanel dealId={dealId} />
          </div>
        </SheetContent>
      </Sheet>

      <GenerateContractDialog
        quoteId={quote?.id ?? null}
        open={contractOpen}
        onOpenChange={setContractOpen}
      />

      <ConfirmActionDialog
        open={sendConfirmOpen}
        onOpenChange={setSendConfirmOpen}
        title={t('confirmActions.sendQuote.title')}
        description={needJustification
          ? t('confirmActions.sendQuote.belowFloorDescription')
          : t('confirmActions.sendQuote.description')}
        variant={needJustification ? 'warning' : 'primary'}
        confirmLabel={t('requestDetailActions.sendQuote')}
        showReason={needJustification}
        requireReason={needJustification}
        reasonLabel={t('confirmActions.sendQuote.justificationLabel')}
        reasonMaxLength={500}
        onConfirm={confirmSend}
        translateError={(code) => translateApiError(code)}
      />

      {/* Unsaved-changes guard for in-app navigation away from the builder (WP-D). */}
      <AlertDialog open={leaveConfirmOpen} onOpenChange={setLeaveConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('quote.builder.leaveTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('quote.builder.leaveDescription')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => { setLeaveConfirmOpen(false); onBack(); }}>
              {t('quote.builder.leaveConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default DealQuotePage;
