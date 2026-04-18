import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useGenerateContract } from '@/hooks/useBilling';

interface GenerateContractDialogProps {
  quoteId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGenerated?: (contractId: number) => void;
}

export function GenerateContractDialog({
  quoteId, open, onOpenChange, onGenerated,
}: GenerateContractDialogProps) {
  const { t } = useTranslation();
  const [notes, setNotes] = useState('');
  const generateMut = useGenerateContract();

  const submit = async () => {
    if (!quoteId) return;
    try {
      const contract = await generateMut.mutateAsync({ quoteId, notes });
      toast.success(t('contractGenerateDialog.success'));
      onGenerated?.(contract.id);
      onOpenChange(false);
      setNotes('');
    } catch (e) {
      toast.error((e as Error).message || t('common.error'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('contractGenerateDialog.title')}</DialogTitle>
          <DialogDescription>{t('contractGenerateDialog.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="notes">{t('contractGenerateDialog.notesLabel')}</Label>
            <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={generateMut.isPending || !quoteId}>
            {t('contractGenerateDialog.generate')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
