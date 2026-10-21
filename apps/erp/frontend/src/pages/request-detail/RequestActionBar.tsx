import { useTranslation } from 'react-i18next';
import { Send, Calculator, ThumbsUp, Loader2, FileText, Handshake, Sparkles, ClipboardCheck, Undo2 } from 'lucide-react';
import type { Quote } from '@/api/crmApi';
import { QuoteStatus } from '@/lib/codes';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';

export interface RequestActionBarProps {
  quote: Quote | null;
  isDraft: boolean;
  isSourcing: boolean;
  isCalculating: boolean;
  isWon: boolean;
  hasQuote: boolean;
  canBuildQuote: boolean;
  /** Право `quote.send`: «Отправить КП» без него закончилось бы 403. */
  canSendQuote: boolean;
  canBuildNewVersion: boolean;
  canClaim: boolean;
  /** Серверная подсказка: зритель вправе вернуть сделку в очередь команды. */
  canRelease: boolean;
  canTakeAndPrepare: boolean;
  canSubmitForReview: boolean;
  changeStagePending: boolean;
  claimPending: boolean;
  releasePending: boolean;
  takePending: boolean;
  submitReviewPending: boolean;
  sendQuotePending: boolean;
  onClaim: () => void;
  onRelease: () => void;
  onTakeAndPrepare: () => void;
  onStartSourcing: () => void;
  onStartCalculation: () => void;
  onOpenGenerate: () => void;
  onOpenQuoteBuilder: () => void;
  onSubmitForReview: () => void;
  onSendQuote: () => void;
  onOpenContract: () => void;
}

/**
 * Action bar for the deal-detail surface (back office). Одобрение / отклонение КП клиентом ушло
 * в Cabinet (M1-ERP-02 волна 3). Returns a hint when there is nothing actionable.
 */
export function RequestActionBar(props: RequestActionBarProps) {
  const { t } = useTranslation();
  const {
    quote, isDraft, isSourcing, isCalculating, isWon,
    hasQuote, canBuildQuote, canSendQuote, canBuildNewVersion, canClaim, canRelease, canTakeAndPrepare, canSubmitForReview,
    changeStagePending, claimPending, releasePending, takePending,
    submitReviewPending, sendQuotePending, onClaim, onRelease, onTakeAndPrepare,
    onStartSourcing, onStartCalculation, onOpenGenerate, onOpenQuoteBuilder, onSubmitForReview,
    onSendQuote, onOpenContract,
  } = props;

  const stageActions = isDraft || isSourcing || isCalculating || hasQuote || canBuildNewVersion;
  const showActionBar = stageActions || isWon || canClaim || canRelease || canTakeAndPrepare || canBuildQuote;

  if (!showActionBar) {
    return <p className="text-sm text-muted-foreground">{t('requestDetailActions.noActions')}</p>;
  }

  return (
    <Card className="bg-muted/30">
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <span className="text-sm font-medium">{t('requestDetailActions.actionsLabel')}:</span>
        {/* W2 «одна кнопка» (one-click-quotation): claim + стадия + предзаполненный КП одним
            действием — короткий путь; только для заявки со строками (FIX-67), иначе сервер откажет. */}
        {canTakeAndPrepare && (
          <Button
            variant="default"
            onClick={onTakeAndPrepare}
            disabled={takePending}
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
            disabled={claimPending}
          >
            {claimPending
              ? <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
              : <Handshake className="h-4 w-4 mr-2" aria-hidden="true" />}
            {t('dealsKanban.claim')}
          </Button>
        )}
        {/* Обратное действие к «Взять в работу»: запись уходит в очередь команды, и её может
            взять любой коллега. Право приходит с сервера — тем же предикатом, что и возврат. */}
        {canRelease && (
          <Button
            variant="ghost"
            onClick={onRelease}
            disabled={releasePending}
          >
            {releasePending
              ? <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
              : <Undo2 className="h-4 w-4 mr-2" aria-hidden="true" />}
            {t('dealsKanban.release')}
          </Button>
        )}
        {isDraft && (
          <Button
            variant="default"
            onClick={onStartSourcing}
            disabled={changeStagePending}
          >
            {t('requestDetailActions.startSourcing')}
          </Button>
        )}
        {isSourcing && (
          <Button
            variant="default"
            onClick={onStartCalculation}
            disabled={changeStagePending}
          >
            <Calculator className="h-4 w-4 mr-2" />
            {t('requestDetailActions.startCalculation')}
          </Button>
        )}
        {/* КП builder entry — create it, then open the focused full-page builder
            (QuoteBuilderGrid: pricing, basis, charges, approval chain). FIX-67: показывается всегда, пока
            КП не начато (при праве на создание КП); рядом с «Взять в работу и подготовить» — вторичной,
            потому что та кнопка есть только у заявки со строками. */}
        {canBuildQuote && (
          <Button
            variant={canTakeAndPrepare ? 'outline' : 'default'}
            onClick={onOpenGenerate}
          >
            <FileText className="h-4 w-4 mr-2" />
            {t('generateQuote.submit')}
          </Button>
        )}
        {/* КП rejected by the client — primary path out of the тупик: start a fresh version
            (backend auto-increments), then open the builder for it. */}
        {canBuildNewVersion && (
          <Button
            variant="default"
            onClick={onOpenGenerate}
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
        {/* Q4: send the DRAFT КП into internal review straight from the request card — no need to
            open the full builder just to start the approval chain. The backend re-runs every gate
            (empty/unpriced/below-cost); a sole-approver КП auto-approves → «Отправить» appears next. */}
        {canSubmitForReview && (
          <Button
            variant="default"
            onClick={onSubmitForReview}
            disabled={submitReviewPending}
          >
            {submitReviewPending
              ? <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
              : <ClipboardCheck className="h-4 w-4 mr-2" aria-hidden="true" />}
            {t('quote.approvalChain.submit')}
          </Button>
        )}
        {/* Only an internally-approved КП can be sent (backend requires READY_TO_SEND). Getting
            there is done via the approval chain on the Deals page; this stays disabled until then. */}
        {quote?.status_code === QuoteStatus.READY_TO_SEND && canSendQuote && (
          <Button
            variant="default"
            onClick={onSendQuote}
            disabled={sendQuotePending}
          >
            <Send className="h-4 w-4 mr-2" />
            {t('requestDetailActions.sendQuote')}
          </Button>
        )}
        {isWon && (
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="outline" className="bg-success/10 text-success border-success/20 py-1.5 px-3">
              <ThumbsUp className="h-4 w-4 mr-2" />
              {t('requestDetailActions.dealAccepted')}
            </Badge>
            {/* The approval auto-materializes the Contract (B1) — carry the user straight to it
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
