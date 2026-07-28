import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AlertTriangle, CheckCircle2, FileText, Loader2, Send, User } from 'lucide-react';
import { type Deal, type Quote } from '@/api/crmApi';
import { useSendQuoteToClient, useUpdateQuoteSettings } from '@/hooks/useCRM';
import { composeSendSummary } from '@/lib/quoteSend';
import { translateApiError, extractApiErrorCode } from '@/lib/apiError';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

interface SendQuoteDialogProps {
  deal: Deal;
  quote: Quote;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Notify the page after a successful send (it owns toast + any follow-up). */
  onSent?: () => void;
}

const pct = (value: string | null): string => (value == null ? '—' : `${Math.round(Number(value) * 10) / 10}%`);

/** One labelled summary row (Odoo composer): a leading label column + the value/control. */
function SummaryRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
      <span className="w-32 shrink-0 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      <div className="min-w-0 flex-1 text-sm">{children}</div>
    </div>
  );
}

/**
 * Wave B2 — unified «Отправить клиенту» composer (Odoo send-composer pattern). ONE action that,
 * before send, summarizes: recipient · validity (editable) · margin vs floor · approval outcome,
 * plus «Предпросмотр PDF» + «Отправить». Reuses the existing send + below-floor-justification
 * wiring (the backend re-checks every gate); this only assembles the pre-send picture.
 */
export function SendQuoteDialog({ deal, quote, open, onOpenChange, onSent }: SendQuoteDialogProps) {
  const { t } = useTranslation();
  const sendQuote = useSendQuoteToClient();
  const updateSettings = useUpdateQuoteSettings();

  const summary = composeSendSummary(deal, quote);
  // Below the margin floor a written justification is required. Two visibility cases: (a) a
  // cost-viewer sees below_floor → prompt up-front; (b) a sender WITHOUT cost rights (economics
  // null) gets prompted REACTIVELY once the backend returns BELOW_FLOOR_JUSTIFICATION_REQUIRED.
  const [justificationRequired, setJustificationRequired] = useState(false);
  const [reason, setReason] = useState('');
  const [validUntil, setValidUntil] = useState(summary.validUntil ?? '');
  const [previewing, setPreviewing] = useState(false);

  // Re-sync the editable validity when a different КП opens the dialog (React reuses the instance).
  useEffect(() => { setValidUntil(quote.valid_until ?? ''); }, [quote.id, quote.valid_until]);

  const needJustification = justificationRequired || summary.marginState === 'below';
  const missingReason = needJustification && !reason.trim();

  // #6 (soft, non-blocking): billable lines the seller never bound to a catalog product. A quote
  // still sends — this is a "you may have skipped matching" nudge, not a gate. SECTION/NOTE carry
  // no product and optional lines are extras, so both are excluded (mirrors the billable() rule).
  const unmatchedLines = (quote.items ?? []).filter(
    (item) => (item.display_type ?? 'ITEM') === 'ITEM' && !item.is_optional && item.product == null,
  ).length;

  const saveValidity = () => {
    const next = validUntil || null;
    if (next === (quote.valid_until ?? null)) return;
    updateSettings.mutate(
      { id: quote.id, data: { valid_until: next } },
      { onError: (err) => toast.error(translateApiError(err)) },
    );
  };

  const preview = async () => {
    // «Предпросмотр PDF» must OPEN the rendered PDF (the 1:1 ground truth), not silently download
    // it — mirrors DocumentActions «Просмотр». Open the blank tab synchronously inside the click
    // gesture (before any await) so the popup blocker doesn't kill it.
    const previewWindow = window.open('', '_blank');
    setPreviewing(true);
    try {
      const { fetchDocumentBlob, openBlobInNewTab } = await import('@/lib/documents');
      const blob = await fetchDocumentBlob(`crm/quotes/${quote.id}/export/`, { export_format: 'pdf' });
      if (!openBlobInNewTab(blob, previewWindow, `RailTech_Quote_${quote.id}.pdf`)) {
        toast.error(t('docActions.popupBlocked'));
      }
    } catch (err) {
      previewWindow?.close();
      toast.error(translateApiError(err));
    } finally {
      setPreviewing(false);
    }
  };

  const send = async () => {
    if (missingReason) return;
    try {
      await sendQuote.mutateAsync({ id: quote.id, justification: reason.trim() || undefined });
      toast.success(t('pages.deals.detail.quoteSentToast'));
      setReason('');
      setJustificationRequired(false);
      onOpenChange(false);
      onSent?.();
    } catch (err) {
      if (extractApiErrorCode(err) === 'BELOW_FLOOR_JUSTIFICATION_REQUIRED') setJustificationRequired(true);
      toast.error(translateApiError(err));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('sendDialog.title')}</DialogTitle>
          <DialogDescription>{t('sendDialog.description')}</DialogDescription>
        </DialogHeader>

        <div className="divide-y">
          {/* Кому */}
          <SummaryRow label={t('sendDialog.recipient')}>
            {summary.recipient ? (
              <span className="inline-flex items-center gap-1.5 font-medium">
                <User className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                {summary.recipient}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-warning">
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                {t('sendDialog.recipientMissing')}
              </span>
            )}
          </SummaryRow>

          {/* Срок действия — editable */}
          <SummaryRow label={t('sendDialog.validUntil')}>
            <div className="flex items-center gap-2">
              <Label htmlFor="send-valid-until" className="sr-only">{t('sendDialog.validUntil')}</Label>
              <Input
                id="send-valid-until"
                type="date"
                value={validUntil}
                onChange={(e) => setValidUntil(e.target.value)}
                onBlur={saveValidity}
                className="h-8 w-auto"
              />
              {updateSettings.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden="true" />}
              {!validUntil && <span className="text-xs text-muted-foreground">{t('sendDialog.validUntilUnset')}</span>}
            </div>
          </SummaryRow>

          {/* Маржа vs порог */}
          <SummaryRow label={t('sendDialog.margin')}>
            {summary.marginState === 'ok' && (
              <span className="inline-flex items-center gap-1.5 text-success">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                {t('sendDialog.marginOk', { margin: pct(summary.marginPercent), floor: pct(summary.floorPercent) })}
              </span>
            )}
            {summary.marginState === 'below' && (
              <span className="inline-flex items-center gap-1.5 text-warning">
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                {t('sendDialog.marginBelow', { margin: pct(summary.marginPercent), floor: pct(summary.floorPercent) })}
              </span>
            )}
            {summary.marginState === 'hidden' && (
              <span className="text-muted-foreground">{t('sendDialog.marginHidden')}</span>
            )}
          </SummaryRow>

          {/* Согласование */}
          <SummaryRow label={t('sendDialog.approval')}>
            {summary.approvalState === 'auto' && (
              <span className="text-muted-foreground">{t('sendDialog.approvalAuto')}</span>
            )}
            {summary.approvalState === 'approved' && (
              <span className="inline-flex items-center gap-1.5 text-success">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                {summary.approvers.length > 0
                  ? t('sendDialog.approvalApprovedBy', { names: summary.approvers.join(', ') })
                  : t('sendDialog.approvalApproved')}
              </span>
            )}
            {summary.approvalState === 'pending' && (
              <span className="text-warning">
                {summary.approvers.length > 0
                  ? t('sendDialog.approvalPendingBy', { names: summary.approvers.join(', ') })
                  : t('sendDialog.approvalPending')}
              </span>
            )}
          </SummaryRow>

          {/* #6 — catalog-match nudge (soft): N billable lines aren't linked to a catalog product.
              Informational only; never blocks the send. */}
          {unmatchedLines > 0 && (
            <SummaryRow label={t('sendDialog.catalogMatch')}>
              <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                <AlertTriangle className="h-3.5 w-3.5 text-warning" aria-hidden="true" />
                {t('sendDialog.unmatchedLines', { count: unmatchedLines })}
              </span>
            </SummaryRow>
          )}

          {/* Below-floor justification — required, recorded in the deal timeline */}
          {needJustification && (
            <div className="py-3">
              <Label htmlFor="send-justification" className="text-xs font-medium">
                {t('confirmActions.sendQuote.justificationLabel')}
              </Label>
              <Textarea
                id="send-justification"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
                rows={3}
                className="mt-1.5"
                aria-invalid={missingReason}
              />
              {missingReason && <p className="mt-1 text-xs text-destructive">{t('sendDialog.justificationRequired')}</p>}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="outline" onClick={preview} disabled={previewing}>
            {previewing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileText className="mr-2 h-4 w-4" />}
            {t('sendDialog.previewPdf')}
          </Button>
          <Button onClick={send} disabled={sendQuote.isPending || missingReason}>
            {sendQuote.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
            {t('requestDetailActions.sendQuote')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default SendQuoteDialog;
