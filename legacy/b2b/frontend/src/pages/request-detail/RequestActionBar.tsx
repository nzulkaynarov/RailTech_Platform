import { useTranslation } from 'react-i18next';
import { Send, Calculator, ThumbsUp, ThumbsDown, Loader2, FileText, Handshake, Sparkles } from 'lucide-react';
import type { Quote } from '@/api/crmApi';
import { QuoteStatus } from '@/lib/codes';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';

export interface RequestActionBarProps {
  quote: Quote | null;
  isSellerSide: boolean;
  isBuyerSide: boolean;
  isDraft: boolean;
  isSourcing: boolean;
  isCalculating: boolean;
  isQuoteSent: boolean;
  isWon: boolean;
  hasQuote: boolean;
  canBuildQuote: boolean;
  canBuildNewVersion: boolean;
  canClaim: boolean;
  canTakeAndPrepare: boolean;
  canEditRequest: boolean;
  isViewer: boolean;
  viewerTip: string;
  changeStagePending: boolean;
  claimPending: boolean;
  takePending: boolean;
  sendQuotePending: boolean;
  approvePending: boolean;
  onClaim: () => void;
  onTakeAndPrepare: () => void;
  onStartSourcing: () => void;
  onStartCalculation: () => void;
  onOpenGenerate: () => void;
  onOpenQuoteBuilder: () => void;
  onSendQuote: () => void;
  onApprove: () => void;
  onReject: () => void;
  onOpenContract: () => void;
}

/**
 * Action bar for the deal-detail surface. Seller-side actions (start sourcing / calculation /
 * send КП) only show for SELLER / MANUFACTURER; the buyer only sees approve / reject once the
 * КП is sent. Returns null when there is nothing actionable (the parent renders wait-hints).
 */
export function RequestActionBar(props: RequestActionBarProps) {
  const { t } = useTranslation();
  const {
    quote, isSellerSide, isBuyerSide, isDraft, isSourcing, isCalculating, isQuoteSent, isWon,
    hasQuote, canBuildQuote, canBuildNewVersion, canClaim, canTakeAndPrepare, canEditRequest,
    isViewer, viewerTip, changeStagePending, claimPending, takePending, sendQuotePending,
    approvePending, onClaim, onTakeAndPrepare, onStartSourcing, onStartCalculation,
    onOpenGenerate, onOpenQuoteBuilder, onSendQuote, onApprove, onReject, onOpenContract,
  } = props;

  const sellerActions = isSellerSide && (isDraft || isSourcing || isCalculating || hasQuote || canBuildNewVersion);
  const buyerActions = isBuyerSide && isQuoteSent && !!quote;
  // Buyer-side "won" state is owned by BuyerAcceptedPanel above, so it does not open an action
  // bar; the seller still gets the "deal accepted / open contract" row from the isWon branch below.
  const showActionBar = sellerActions || buyerActions || (isWon && isSellerSide) || canClaim || canTakeAndPrepare;

  if (!showActionBar) {
    // A buyer editing a draft already gets this guidance from the "Your request" card subtitle —
    // don't waste a whole banner repeating it; the post-accept panel already speaks for the won state.
    if (isBuyerSide && (canEditRequest || isWon)) return null;
    return (
      <p className="text-sm text-muted-foreground">
        {isBuyerSide ? t('requestDetailActions.buyerWaitHint') : t('requestDetailActions.noActions')}
      </p>
    );
  }

  return (
    <Card className="bg-muted/30">
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <span className="text-sm font-medium">{t('requestDetailActions.actionsLabel')}:</span>
        {/* W2 «одна кнопка» (one-click-quotation): claim + стадия + предзаполненный КП одним
            действием — короткий путь; кнопки ниже остаются для пошагового сценария. */}
        {canTakeAndPrepare && (
          <Button
            variant="default"
            onClick={onTakeAndPrepare}
            disabled={isViewer || takePending}
            title={isViewer ? viewerTip : undefined}
          >
            {takePending
              ? <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
              : <Sparkles className="h-4 w-4 mr-2" aria-hidden="true" />}
            {takePending ? t('requestDetailActions.takePreparing') : t('requestDetailActions.takeAndPrepare')}
          </Button>
        )}
        {canClaim && (
          <Button
            variant="outline"
            onClick={onClaim}
            disabled={isViewer || claimPending}
            title={isViewer ? viewerTip : undefined}
          >
            {claimPending
              ? <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
              : <Handshake className="h-4 w-4 mr-2" aria-hidden="true" />}
            {t('dealsKanban.claim')}
          </Button>
        )}
        {isSellerSide && isDraft && (
          <Button
            variant="default"
            onClick={onStartSourcing}
            disabled={isViewer || changeStagePending}
            title={isViewer ? viewerTip : undefined}
          >
            {t('requestDetailActions.startSourcing')}
          </Button>
        )}
        {isSellerSide && isSourcing && (
          <Button
            variant="default"
            onClick={onStartCalculation}
            disabled={isViewer || changeStagePending}
            title={isViewer ? viewerTip : undefined}
          >
            <Calculator className="h-4 w-4 mr-2" />
            {t('requestDetailActions.startCalculation')}
          </Button>
        )}
        {/* КП builder entry — create it, then open the focused full-page builder
            (QuoteBuilderGrid: pricing, basis, charges, approval chain). */}
        {canBuildQuote && (
          <Button
            variant="default"
            onClick={onOpenGenerate}
            disabled={isViewer}
            title={isViewer ? viewerTip : undefined}
          >
            <FileText className="h-4 w-4 mr-2" />
            {t('generateQuote.submit')}
          </Button>
        )}
        {/* КП rejected by the buyer — primary path out of the тупик: start a fresh version
            (backend auto-increments), then open the builder for it. */}
        {canBuildNewVersion && (
          <Button
            variant="default"
            onClick={onOpenGenerate}
            disabled={isViewer}
            title={isViewer ? viewerTip : undefined}
          >
            <FileText className="h-4 w-4 mr-2" />
            {t('requestDetailActions.newQuoteVersion')}
          </Button>
        )}
        {hasQuote && (
          <Button variant="outline" onClick={onOpenQuoteBuilder}>
            <FileText className="h-4 w-4 mr-2" />
            {t('pages.deals.detail.openQuote')}
          </Button>
        )}
        {/* Only an internally-approved КП can be sent (backend requires READY_TO_SEND). Getting
            there is done via the approval chain on the Deals page; this stays disabled until then. */}
        {isSellerSide && quote?.status_code === QuoteStatus.READY_TO_SEND && (
          <Button
            variant="default"
            onClick={onSendQuote}
            disabled={isViewer || sendQuotePending}
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
              onClick={onApprove}
              disabled={isViewer || approvePending}
              title={isViewer ? viewerTip : undefined}
            >
              <ThumbsUp className="h-4 w-4 mr-2" />
              {t('requestDetailActions.approveQuote')}
            </Button>
            <Button
              variant="destructive"
              onClick={onReject}
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
            {/* The approval auto-materializes the Contract (B1) — carry the buyer straight to it
                instead of a terminal badge with no next step (audit B2). */}
            <Button size="sm" onClick={onOpenContract}>
              <FileText className="h-4 w-4 mr-2" />
              {t('requestDetailActions.openContract')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default RequestActionBar;
