import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

interface RejectQuoteDialogProps {
  quoteId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with a non-empty reason — the backend service rejectQuote will see it. */
  onConfirm: (reason: string) => Promise<void>;
}

export function RejectQuoteDialog({ quoteId, open, onOpenChange, onConfirm }: RejectQuoteDialogProps) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!reason.trim()) {
      toast.error(t('requestDetailActions.rejectDialog.reasonRequired'));
      return;
    }
    setBusy(true);
    try {
      await onConfirm(reason.trim());
      setReason('');
      onOpenChange(false);
    } catch (e) {
      toast.error(translateApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('requestDetailActions.rejectDialog.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('requestDetailActions.rejectDialog.description')}
            {quoteId != null ? ` · Quote #${quoteId}` : ''}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <Label htmlFor="reject-reason">{t('requestDetailActions.rejectDialog.reasonLabel')}</Label>
          <Textarea
            id="reject-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('requestDetailActions.rejectDialog.reasonPlaceholder')}
            rows={4}
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction onClick={submit} disabled={busy}>
            {t('requestDetailActions.rejectDialog.confirm')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
