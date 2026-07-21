import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CheckCircle2, ChevronRight, Copy, Eye, FilePlus2, Link2Off, Loader2, Send, XCircle } from 'lucide-react';
import type { Deal, Quote } from '@/api/crmApi';
import { publicQuoteUrl, resolveDecision } from '@/lib/quoteSend';
import { useRevokePublicLink, useCreateQuote } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface QuoteSentPanelProps {
  deal: Deal;
  quote: Quote;
}

const fmtDateTime = (iso: string | null | undefined): string =>
  (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) : '');

/** One stage of the tracking line: label + value + optional accent color. */
function Stage({ label, value, tone, icon }: { label: string; value: string; tone?: 'success' | 'destructive'; icon?: React.ReactNode }) {
  const toneClass = tone === 'success' ? 'text-success' : tone === 'destructive' ? 'text-destructive' : 'text-foreground';
  return (
    <div className="flex min-w-0 flex-col">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={`inline-flex items-center gap-1 text-sm font-medium ${toneClass}`}>
        {icon}
        {value}
      </span>
    </div>
  );
}

/**
 * Wave B2 — post-send tracking panel (PandaDoc pattern). Replaces the silent «КП отправлено»
 * state once a КП is SENT: a live status line (Отправлено → Просмотрено → Решение) plus low-key
 * actions (копировать / отозвать публичную ссылку, создать новую версию). Every action degrades
 * gracefully — the link controls appear only when the backend exposes the share token.
 */
export function QuoteSentPanel({ deal, quote }: QuoteSentPanelProps) {
  const { t } = useTranslation();
  const revoke = useRevokePublicLink();
  const createQuote = useCreateQuote();
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [newVersionOpen, setNewVersionOpen] = useState(false);

  const decision = resolveDecision(quote.status_code);
  const viewed = quote.first_viewed_at ?? null;
  const link = publicQuoteUrl(quote.public_access_token, window.location.origin);
  const linkActive = !!link && !quote.public_token_revoked;

  const decisionValue =
    decision === 'accepted' ? t('sentPanel.decisionAccepted')
      : decision === 'rejected' ? t('sentPanel.decisionRejected')
        : t('sentPanel.pending');

  const copyLink = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      toast.success(t('docActions.linkCopied'));
    } catch {
      toast.error(t('errors.operationFailed'));
    }
  };

  const confirmRevoke = () => {
    revoke.mutate(quote.id, {
      onSuccess: () => { toast.success(t('sentPanel.linkRevoked')); setRevokeOpen(false); },
      onError: (err) => toast.error(translateApiError(err)),
    });
  };

  const confirmNewVersion = () => {
    createQuote.mutate(
      { deal: deal.id },
      {
        onSuccess: () => { toast.success(t('sentPanel.newVersionCreated')); setNewVersionOpen(false); },
        onError: (err) => toast.error(translateApiError(err)),
      },
    );
  };

  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      {/* Tracking line: Отправлено → Просмотрено → Решение */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Stage
          label={t('sentPanel.sent')}
          value={fmtDateTime(quote.frozen_at) || t('sentPanel.yes')}
          icon={<Send className="h-3.5 w-3.5" aria-hidden="true" />}
        />
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <Stage
          label={t('sentPanel.viewed')}
          value={viewed ? fmtDateTime(viewed) : t('sentPanel.pending')}
          tone={viewed ? 'success' : undefined}
          icon={viewed ? <Eye className="h-3.5 w-3.5" aria-hidden="true" /> : undefined}
        />
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <Stage
          label={t('sentPanel.decision')}
          value={decisionValue}
          tone={decision === 'accepted' ? 'success' : decision === 'rejected' ? 'destructive' : undefined}
          icon={decision === 'accepted' ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            : decision === 'rejected' ? <XCircle className="h-3.5 w-3.5" aria-hidden="true" /> : undefined}
        />
      </div>

      {/* Low-key actions */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
        {linkActive && (
          <>
            <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={copyLink}>
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              {t('sentPanel.copyLink')}
            </Button>
            <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => setRevokeOpen(true)} disabled={revoke.isPending}>
              {revoke.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Link2Off className="h-3.5 w-3.5" aria-hidden="true" />}
              {t('sentPanel.revokeLink')}
            </Button>
          </>
        )}
        {!!link && quote.public_token_revoked && (
          <span className="text-xs text-muted-foreground">{t('sentPanel.linkRevokedNote')}</span>
        )}
        <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => setNewVersionOpen(true)} disabled={createQuote.isPending}>
          {createQuote.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FilePlus2 className="h-3.5 w-3.5" aria-hidden="true" />}
          {t('sentPanel.newVersion')}
        </Button>
      </div>

      <AlertDialog open={revokeOpen} onOpenChange={setRevokeOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('sentPanel.revokeTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('sentPanel.revokeDescription')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={revoke.isPending}>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={(e) => { e.preventDefault(); confirmRevoke(); }} disabled={revoke.isPending}>
              {t('common.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={newVersionOpen} onOpenChange={setNewVersionOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('sentPanel.newVersionTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('sentPanel.newVersionDescription')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={createQuote.isPending}>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={(e) => { e.preventDefault(); confirmNewVersion(); }} disabled={createQuote.isPending}>
              {t('sentPanel.newVersion')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default QuoteSentPanel;
