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

interface RejectActDialogProps {
  actNumber: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Вызывается с непустой причиной — бэкенд отвергает пустую кодом REASON_REQUIRED. */
  onConfirm: (reason: string) => Promise<void>;
}

/**
 * Заказчик возвращает акт исполнителю с причиной — второй шаг двустороннего цикла (G2).
 *
 * Раньше выразить несогласие было нечем: акт можно было только подписать, поэтому спорный
 * документ просто повисал. Паттерн взят у ЭСФ («подтвердить или отклонить») и у соседнего
 * отклонения КП, где причина тоже обязательна: без основания отказ бесполезен обеим сторонам.
 */
export function RejectActDialog({ actNumber, open, onOpenChange, onConfirm }: RejectActDialogProps) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!reason.trim()) {
      toast.error(t('actsPage.rejectDialog.reasonRequired'));
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
          <AlertDialogTitle>{t('actsPage.rejectDialog.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('actsPage.rejectDialog.description')}
            {actNumber ? ` · ${actNumber}` : ''}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <Label htmlFor="reject-act-reason">{t('actsPage.rejectDialog.reasonLabel')}</Label>
          <Textarea
            id="reject-act-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('actsPage.rejectDialog.reasonPlaceholder')}
            rows={4}
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction onClick={submit} disabled={busy}>
            {t('actsPage.rejectDialog.confirm')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default RejectActDialog;
