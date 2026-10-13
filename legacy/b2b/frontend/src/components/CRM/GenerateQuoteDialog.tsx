import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2, FileText, CheckCircle2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useCreateQuote } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';

interface GenerateQuoteDialogProps {
  dealId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGenerated?: (quoteId: number) => void;
}

/**
 * SELLER "Build quote" dialog. Creates a DRAFT Quote for a deal, optionally
 * sends it to the client immediately (triggers PDF generation + FSM
 * transition to QUOTE_SENT). Editable quote items happen on the deal detail
 * page / QuoteBuilderGrid — this dialog is only the entry point.
 */
export function GenerateQuoteDialog({ dealId, open, onOpenChange, onGenerated }: GenerateQuoteDialogProps) {
  const { t } = useTranslation();
  const [notes, setNotes] = useState('');
  // valid_until is no longer edited here (S2: it lives only in «Настройки КП»). Creation still
  // pre-fills a silent +14-day default so the КП is born with a validity; the seller adjusts it
  // later in settings.
  const [validUntil] = useState<string>(() => {
    const defaultDate = new Date();
    defaultDate.setDate(defaultDate.getDate() + 14);
    return defaultDate.toISOString().slice(0, 10);
  });
  const createMut = useCreateQuote();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!dealId) return;
    try {
      const quote = await createMut.mutateAsync({
        deal: dealId,
        notes: notes.trim() || undefined,
        valid_until: validUntil || undefined,
      });
      toast.success(t('generateQuote.created'));
      onGenerated?.(quote.id);
      onOpenChange(false);
      setNotes('');
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  const busy = createMut.isPending;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!busy) onOpenChange(v);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" aria-hidden="true" />
              {t('generateQuote.title')}
            </DialogTitle>
            <DialogDescription>{t('generateQuote.description')}</DialogDescription>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="generate-quote-notes">
                {t('generateQuote.fields.notes')}
              </Label>
              <Textarea
                id="generate-quote-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t('generateQuote.fields.notesPlaceholder')}
                rows={3}
                maxLength={2000}
              />
            </div>
            <div className="rounded-md border bg-muted/30 p-2 text-xs">
              <div className="flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                {t('generateQuote.nextSteps.title')}
              </div>
              <ol className="mt-1 list-decimal pl-5 text-muted-foreground">
                <li>{t('generateQuote.nextSteps.item1')}</li>
                <li>{t('generateQuote.nextSteps.item2')}</li>
                <li>{t('generateQuote.nextSteps.item3')}</li>
              </ol>
            </div>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={busy || !dealId}>
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : null}
              {t('generateQuote.submit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
