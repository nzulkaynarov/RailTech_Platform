import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useDeals, useCreateQuote } from '@/hooks/useCRM';

interface CreateQuoteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateQuoteDialog({ open, onOpenChange }: CreateQuoteDialogProps) {
  const { t } = useTranslation();
  const { data: deals } = useDeals();
  const createMut = useCreateQuote();
  const [dealId, setDealId] = useState<string>('');
  const [notes, setNotes] = useState('');
  const [validUntil, setValidUntil] = useState('');

  // Only deals that are not already closed — we can build a new Quote on them.
  const eligibleDeals = (deals ?? []).filter(
    (d) => !['CLOSED_WON', 'CLOSED_LOST'].includes(d.stage_code ?? ''),
  );

  const submit = async () => {
    if (!dealId) {
      toast.error(t('createQuoteDialog.dealRequired'));
      return;
    }
    try {
      const quote = await createMut.mutateAsync({
        deal: Number(dealId),
        notes,
        valid_until: validUntil || undefined,
      });
      toast.success(t('createQuoteDialog.created', { version: quote.version }));
      onOpenChange(false);
      setDealId('');
      setNotes('');
      setValidUntil('');
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('createQuoteDialog.title')}</DialogTitle>
          <DialogDescription>{t('createQuoteDialog.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="cq-deal">{t('createQuoteDialog.deal')}</Label>
            <Select value={dealId} onValueChange={setDealId}>
              <SelectTrigger id="cq-deal">
                <SelectValue placeholder={t('createQuoteDialog.selectDeal')} />
              </SelectTrigger>
              <SelectContent>
                {eligibleDeals.map((d) => (
                  <SelectItem key={d.id} value={String(d.id)}>
                    #{d.id} · {d.title || d.company_name || ''} · {d.stage_code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="cq-valid">{t('createQuoteDialog.validUntil')}</Label>
            <Input
              id="cq-valid"
              type="date"
              value={validUntil}
              onChange={(e) => setValidUntil(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="cq-notes">{t('createQuoteDialog.notes')}</Label>
            <Textarea
              id="cq-notes"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={createMut.isPending || !dealId}>
            {t('createQuoteDialog.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
