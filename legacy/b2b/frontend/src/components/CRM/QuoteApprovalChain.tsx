import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Check, ChevronRight, Loader2, SendHorizontal, Undo2 } from 'lucide-react';
import type { Quote } from '@/api/crmApi';
import { useAuthStore } from '@/store/authStore';
import { translateApiError } from '@/lib/apiError';
import {
  useSubmitQuoteForReview,
  useConfirmQuoteTradeReview,
  useDirectorApproveQuote,
  useSendQuoteBack,
} from '@/hooks/useCRM';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface QuoteApprovalChainProps {
  quote: Quote;
}

/** Ordered chain stages, used to render the stepper. SENT/APPROVED/REJECTED are
 * terminal client-side states — the chain bar hides itself for them. */
const CHAIN_STEPS = [
  { code: 'DRAFT', labelKey: 'quote.approvalChain.stepDraft' },
  { code: 'PENDING_TRADE_REVIEW', labelKey: 'quote.approvalChain.stepTradeReview' },
  { code: 'PENDING_APPROVAL', labelKey: 'quote.approvalChain.stepApproval' },
  { code: 'READY_TO_SEND', labelKey: 'quote.approvalChain.stepReady' },
] as const;

const CHAIN_STATUSES = new Set<string>(CHAIN_STEPS.map((s) => s.code));

/** OWNER is the escape hatch — it can advance any step (mirrors the backend
 * `has_workspace_role`). Each forward action also lists its dedicated role. */
const canAct = (role: string | null | undefined, allowed: string[]): boolean =>
  !!role && (role === 'OWNER' || allowed.includes(role));

/**
 * КП internal approval chain (документооборот) bar for the seller team.
 * Renders the stepper + the single forward action matching the current status,
 * gated by the member's primary-company workspace role. The backend re-checks
 * the role against the КП's owning company, so this only drives what's shown.
 */
export const QuoteApprovalChain: React.FC<QuoteApprovalChainProps> = ({ quote }) => {
  const { t } = useTranslation();
  const workspaceRole = useAuthStore((s) => s.user?.workspace_role);

  const submit = useSubmitQuoteForReview();
  const confirmTrade = useConfirmQuoteTradeReview();
  const directorApprove = useDirectorApproveQuote();
  const sendBack = useSendQuoteBack();

  const [sendBackOpen, setSendBackOpen] = useState(false);
  const [reason, setReason] = useState('');

  const status = quote.status_code;
  if (!CHAIN_STATUSES.has(status)) return null;

  const activeIndex = CHAIN_STEPS.findIndex((s) => s.code === status);
  const busy = submit.isPending || confirmTrade.isPending || directorApprove.isPending || sendBack.isPending;

  const run = async (mutate: () => Promise<unknown>, successKey: string) => {
    try {
      await mutate();
      toast.success(t(successKey));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const confirmSendBack = async () => {
    try {
      await sendBack.mutateAsync({ id: quote.id, reason: reason.trim() });
      toast.success(t('quote.approvalChain.sentBack'));
      setReason('');
      setSendBackOpen(false);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  // Forward action for the current step — only the responsible role sees it.
  const forwardAction = (() => {
    if (status === 'DRAFT' && canAct(workspaceRole, ['SALES_MANAGER'])) {
      return (
        <Button size="sm" disabled={busy}
          onClick={() => run(() => submit.mutateAsync(quote.id), 'quote.approvalChain.submitted')}>
          {submit.isPending ? <Loader2 className="size-3 animate-spin" /> : <SendHorizontal className="size-3" />}
          {t('quote.approvalChain.submit')}
        </Button>
      );
    }
    if (status === 'PENDING_TRADE_REVIEW' && canAct(workspaceRole, ['FOREIGN_TRADE_SPECIALIST'])) {
      return (
        <Button size="sm" disabled={busy}
          onClick={() => run(() => confirmTrade.mutateAsync(quote.id), 'quote.approvalChain.tradeConfirmed')}>
          {confirmTrade.isPending ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
          {t('quote.approvalChain.confirmTradeReview')}
        </Button>
      );
    }
    if (status === 'PENDING_APPROVAL' && canAct(workspaceRole, ['DIRECTOR'])) {
      return (
        <Button size="sm" disabled={busy}
          onClick={() => run(() => directorApprove.mutateAsync(quote.id), 'quote.approvalChain.approved')}>
          {directorApprove.isPending ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
          {t('quote.approvalChain.directorApprove')}
        </Button>
      );
    }
    return null;
  })();

  // Send-back is available to ВЭД / DIRECTOR (and OWNER) on any review state.
  const showSendBack =
    status !== 'DRAFT' && canAct(workspaceRole, ['FOREIGN_TRADE_SPECIALIST', 'DIRECTOR']);

  // A hint shown when the current user is not the one who must act now.
  const waitingHint = (() => {
    if (forwardAction) return null;
    if (status === 'PENDING_TRADE_REVIEW') return t('quote.approvalChain.waitingTradeReview');
    if (status === 'PENDING_APPROVAL') return t('quote.approvalChain.waitingApproval');
    if (status === 'READY_TO_SEND') return t('quote.approvalChain.readyHint');
    return null;
  })();

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/40 px-3 py-2">
      <span className="text-xs font-semibold text-muted-foreground shrink-0">
        {t('quote.approvalChain.title')}
      </span>

      {/* Stepper */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {CHAIN_STEPS.map((step, idx) => {
          const isDone = idx < activeIndex;
          const isActive = idx === activeIndex;
          return (
            <React.Fragment key={step.code}>
              <Badge
                variant={isActive ? 'default' : isDone ? 'secondary' : 'outline'}
                className={cn('gap-1', !isActive && !isDone && 'text-muted-foreground')}
              >
                {isDone && <Check className="size-3" />}
                {t(step.labelKey)}
              </Badge>
              {idx < CHAIN_STEPS.length - 1 && (
                <ChevronRight className="size-3 text-muted-foreground shrink-0" />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {waitingHint && (
        <span className="text-xs text-muted-foreground">{waitingHint}</span>
      )}

      {/* Actions */}
      <div className="flex items-center gap-1.5 ml-auto">
        {showSendBack && (
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setSendBackOpen(true)}>
            <Undo2 className="size-3" />
            {t('quote.approvalChain.sendBack')}
          </Button>
        )}
        {forwardAction}
      </div>

      <AlertDialog open={sendBackOpen} onOpenChange={(o) => { if (!o) setReason(''); setSendBackOpen(o); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('quote.approvalChain.sendBackTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('quote.approvalChain.sendBackDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="send-back-reason">{t('quote.approvalChain.sendBack')}</Label>
            <Textarea
              id="send-back-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t('quote.approvalChain.sendBackReasonPlaceholder')}
              rows={3}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={sendBack.isPending}>{t('common.cancel')}</AlertDialogCancel>
            <Button onClick={confirmSendBack} disabled={sendBack.isPending}>
              {sendBack.isPending && <Loader2 className="size-3 animate-spin" />}
              {t('quote.approvalChain.sendBack')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
