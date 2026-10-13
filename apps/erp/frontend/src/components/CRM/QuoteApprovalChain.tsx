import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Check, ChevronDown, Clock, Loader2, Lock, SendHorizontal, Undo2, X, Mail } from 'lucide-react';
import type { Quote, QuoteApprovalStep } from '@/api/crmApi';
import { translateApiError } from '@/lib/apiError';
import { useQuoteApprovalPreview, useSubmitQuoteForReview, useActOnApprovalStep, useRecallQuote } from '@/hooks/useCRM';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface QuoteApprovalChainProps {
  quote: Quote;
}

const CHAIN_STATUSES = new Set(['DRAFT', 'PENDING_APPROVAL', 'READY_TO_SEND']);

const STATUS_ICON: Record<string, React.ReactNode> = {
  APPROVED: <Check className="size-3.5 text-success" aria-hidden="true" />,
  REJECTED: <X className="size-3.5 text-destructive" aria-hidden="true" />,
  PENDING: <Clock className="size-3.5 text-warning" aria-hidden="true" />,
  RECALLED: <Undo2 className="size-3.5 text-muted-foreground" aria-hidden="true" />,
  SKIPPED: <Check className="size-3.5 text-muted-foreground" aria-hidden="true" />,
};

/**
 * КП internal approval chain (unified workflow) — the step list a КП routes through:
 * intermediate approvers + a mandatory head, optionally an «informed» CC group. Renders
 * submit (DRAFT), per-step approve/reject for whoever may act now, and recall. Backend
 * re-checks every permission, so this only drives what's shown.
 *
 * Rendered as a compact status pill + Popover for the workspace top toolbar (the only live
 * call site) — so the always-open chain never costs ~100px of vertical budget.
 */
export const QuoteApprovalChain: React.FC<QuoteApprovalChainProps> = ({ quote }) => {
  const { t } = useTranslation();
  const submit = useSubmitQuoteForReview();
  const act = useActOnApprovalStep();
  const recall = useRecallQuote();

  const [rejectStep, setRejectStep] = useState<QuoteApprovalStep | null>(null);
  const [reason, setReason] = useState('');

  const status = quote.status_code;
  // DRAFT: read-only preview of the would-be chain — the seller sees up-front who will approve
  // (or that it will auto-approve) BEFORE committing to submit. No side effects (Salesforce
  // Approval Preview). Hook order is unconditional (rules-of-hooks); the fetch itself is gated
  // to drafts via `enabled`.
  const { data: approvalPreview } = useQuoteApprovalPreview(quote.id, status === 'DRAFT');
  if (!CHAIN_STATUSES.has(status)) return null;

  const steps = quote.approval_steps ?? [];
  const busy = submit.isPending || act.isPending || recall.isPending;
  // Decided/total for the compact «шаг k/n» progress hint (PENDING is the only undecided state).
  const decidedCount = steps.filter((s) => s.status !== 'PENDING').length;
  const actionableStep = steps.find((s) => s.can_act) ?? null;

  const run = async (fn: () => Promise<unknown>, successKey: string) => {
    try {
      await fn();
      toast.success(t(successKey));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const approve = (step: QuoteApprovalStep) =>
    run(() => act.mutateAsync({ id: quote.id, stepId: step.id, decision: 'APPROVE' }), 'quote.approvalChain.approved');

  const submitForReview = () => run(() => submit.mutateAsync(quote.id), 'quote.approvalChain.submitted');

  const confirmReject = async () => {
    if (!rejectStep) return;
    try {
      await act.mutateAsync({ id: quote.id, stepId: rejectStep.id, decision: 'REJECT', comment: reason.trim() });
      toast.success(t('quote.approvalChain.rejected'));
      setRejectStep(null);
      setReason('');
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const groups: { key: string; labelKey: string; icon: React.ReactNode; items: QuoteApprovalStep[] }[] = [
    { key: 'APPROVER', labelKey: 'quote.approvalChain.groupApprovers', icon: null, items: steps.filter((s) => s.participation === 'APPROVER') },
    { key: 'HEAD', labelKey: 'quote.approvalChain.groupHead', icon: <Lock className="size-3" />, items: steps.filter((s) => s.participation === 'HEAD') },
    { key: 'INFORMED', labelKey: 'quote.approvalChain.groupInformed', icon: <Mail className="size-3" />, items: steps.filter((s) => s.participation === 'INFORMED') },
  ];

  const renderStep = (step: QuoteApprovalStep) => (
    <div key={step.id} className="flex flex-wrap items-center gap-2 py-1 text-sm">
      {STATUS_ICON[step.status]}
      <span className="font-medium">{step.approver_name || t('quote.approvalChain.anyHolder')}</span>
      {step.is_mandatory && <Lock className="size-3 text-muted-foreground" aria-label={t('quote.approvalChain.mandatory')} />}
      <Badge variant="outline" className="text-xs">{t(`quote.approvalChain.stepStatus.${step.status}`)}</Badge>
      {step.acted_by_name && step.decided_at && (
        <span className="text-xs text-muted-foreground">
          {step.acted_by_name} · {new Date(step.decided_at).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })}
        </span>
      )}
      {step.comment && <span className="text-xs text-muted-foreground">«{step.comment}»</span>}
      {step.can_act && (
        <span className="ml-auto flex gap-1.5">
          <Button size="sm" disabled={busy} onClick={() => approve(step)}>
            {act.isPending ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
            {t('quote.approvalChain.approve')}
          </Button>
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setRejectStep(step)}>
            <Undo2 className="size-3" />
            {t('quote.approvalChain.reject')}
          </Button>
        </span>
      )}
    </div>
  );

  // The top action row (submit on DRAFT / recall on PENDING) — shared by full + compact bodies.
  const primaryAction = (
    <>
      {status === 'DRAFT' && (
        <Button size="sm" disabled={busy} onClick={submitForReview}>
          {submit.isPending ? <Loader2 className="size-3 animate-spin" /> : <SendHorizontal className="size-3" />}
          {t('quote.approvalChain.submit')}
        </Button>
      )}
      {status === 'PENDING_APPROVAL' && (
        <Button variant="outline" size="sm" disabled={busy}
          onClick={() => run(() => recall.mutateAsync(quote.id), 'quote.approvalChain.recalled')}>
          <Undo2 className="size-3" />
          {t('quote.approvalChain.recall')}
        </Button>
      )}
    </>
  );

  // The step list / status body — identical in the inline bar and the compact popover.
  const chainBody = (
    <>
      {status === 'DRAFT' && approvalPreview && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('quote.approvalChain.previewTitle')}
          </p>
          {approvalPreview.would_auto_approve ? (
            <p className="text-xs text-muted-foreground">{t('quote.approvalChain.previewAuto')}</p>
          ) : (
            <div className="rounded-md border bg-background px-3 py-1.5">
              {approvalPreview.steps.map((step, index) => (
                <div key={index} className="flex items-center gap-2 py-1 text-xs">
                  <Clock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className="font-medium">{step.name}</span>
                  <span className="text-muted-foreground">
                    {step.role ? `${step.role} · ` : ''}{step.participation_label}
                  </span>
                </div>
              ))}
            </div>
          )}
          {approvalPreview.below_floor && (
            <p className="text-xs text-warning">{t('quote.approvalChain.previewBelowFloor')}</p>
          )}
        </div>
      )}

      {status === 'PENDING_APPROVAL' && steps.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">{t('quote.approvalChain.pendingApprovalHelper')}</p>
          {groups.filter((g) => g.items.length > 0).map((group) => (
            <div key={group.key} className="rounded-md border bg-background px-3 py-1.5">
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group.icon}{t(group.labelKey)}
              </div>
              {group.items.sort((a, b) => a.order - b.order).map(renderStep)}
            </div>
          ))}
        </div>
      )}

      {status === 'READY_TO_SEND' && (
        <span className="text-xs text-muted-foreground">{t('quote.approvalChain.readyHint')}</span>
      )}
    </>
  );

  const rejectDialog = (
    <AlertDialog open={!!rejectStep} onOpenChange={(o) => { if (!o) { setRejectStep(null); setReason(''); } }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('quote.approvalChain.rejectTitle')}</AlertDialogTitle>
          <AlertDialogDescription>{t('quote.approvalChain.rejectDesc')}</AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <Label htmlFor="reject-reason">{t('quote.approvalChain.comment')}</Label>
          <Textarea id="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={t('quote.approvalChain.rejectReasonPlaceholder')} rows={3} />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={act.isPending}>{t('common.cancel')}</AlertDialogCancel>
          <Button variant="destructive" onClick={confirmReject} disabled={act.isPending}>
            {act.isPending && <Loader2 className="size-3 animate-spin" />}
            {t('quote.approvalChain.reject')}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  const statusBadge = (
    <Badge variant={status === 'READY_TO_SEND' ? 'secondary' : 'default'} className="text-xs">
      {t(`quote.approvalChain.status.${status}`)}
    </Badge>
  );

  // A status pill + Popover for the workspace top toolbar.
  return (
    <div className="flex items-center gap-1.5">
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="h-8 gap-1.5" aria-label={t('quote.builder.openApproval')}>
            {statusBadge}
            {steps.length > 0 && (
              <span className="text-xs text-muted-foreground">
                {t('quote.approvalChain.stepProgress', { current: decidedCount, total: steps.length })}
              </span>
            )}
            <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden="true" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-96 max-w-[92vw]">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-muted-foreground">{t('quote.approvalChain.title')}</span>
              <div className="flex items-center gap-1.5">{primaryAction}</div>
            </div>
            {chainBody}
          </div>
        </PopoverContent>
      </Popover>
      {/* Duplicate the current user's actionable step next to the pill — one-click approve
          without opening the popover (reject still routes through the popover). */}
      {actionableStep && (
        <Button size="sm" className="h-8" disabled={busy} onClick={() => approve(actionableStep)}>
          {act.isPending ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
          {t('quote.approvalChain.approve')}
        </Button>
      )}
      {rejectDialog}
    </div>
  );
};
