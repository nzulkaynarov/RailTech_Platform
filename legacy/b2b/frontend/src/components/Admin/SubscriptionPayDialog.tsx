import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { usePaySubscription } from '@/hooks/useAccounts';

interface SubscriptionPayDialogProps {
  subscriptionId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SubscriptionPayDialog({
  subscriptionId, open, onOpenChange,
}: SubscriptionPayDialogProps) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState('0');
  const [months, setMonths] = useState('1');
  const payMut = usePaySubscription();

  const submit = async () => {
    if (!subscriptionId) return;
    try {
      await payMut.mutateAsync({
        id: subscriptionId,
        amount,
        months: Number(months) || 1,
      });
      toast.success(t('subscriptionPay.paid'));
      onOpenChange(false);
      setAmount('0');
      setMonths('1');
    } catch (e) {
      toast.error((e as Error).message || t('common.error'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('subscriptionPay.title')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <ManualModeBanner kind="payment" />
          <div>
            <Label htmlFor="pay-amount">{t('subscriptionPay.amount')}</Label>
            <Input
              id="pay-amount"
              type="number"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="pay-months">{t('subscriptionPay.months')}</Label>
            <Input
              id="pay-months"
              type="number"
              min="1"
              value={months}
              onChange={(e) => setMonths(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={payMut.isPending || !subscriptionId}>
            {t('subscriptionPay.pay')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
