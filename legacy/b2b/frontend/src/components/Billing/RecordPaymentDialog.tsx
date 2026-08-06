import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2, Wallet, Upload, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { useInvoices, useRecordPayment } from '@/hooks/useBilling';
import { translateApiError } from '@/lib/apiError';

interface RecordPaymentDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Preselected invoice id — useful when opened from invoice detail. */
  defaultInvoiceId?: number;
  onRecorded?: () => void;
}

const METHODS: Array<'BANK_TRANSFER' | 'CARD' | 'CASH' | 'OTHER'> = [
  'BANK_TRANSFER', 'CARD', 'CASH', 'OTHER',
];

export function RecordPaymentDialog({
  open,
  onOpenChange,
  defaultInvoiceId,
  onRecorded,
}: RecordPaymentDialogProps) {
  const { t } = useTranslation();
  const recordMut = useRecordPayment();
  const { data: invoices = [], isLoading: invoicesLoading } = useInvoices({
    status: 'ISSUED,PARTIAL,OVERDUE',
  });

  const [invoiceId, setInvoiceId] = useState<string>(defaultInvoiceId ? String(defaultInvoiceId) : '');
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState<'BANK_TRANSFER' | 'CARD' | 'CASH' | 'OTHER'>('BANK_TRANSFER');
  const [paidAt, setPaidAt] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [reference, setReference] = useState('');
  const [proofFile, setProofFile] = useState<File | null>(null);

  const payableInvoices = useMemo(
    () => invoices.filter((i) => ['ISSUED', 'PARTIAL', 'OVERDUE'].includes(i.status)),
    [invoices],
  );

  const selectedInvoice = useMemo(
    () => payableInvoices.find((i) => String(i.id) === invoiceId) ?? null,
    [payableInvoices, invoiceId],
  );

  const balanceDueStr = selectedInvoice?.balance_due ?? '';
  const balanceDue = Number(balanceDueStr) || 0;

  // Диалог смонтирован ВМЕСТЕ со страницей, поэтому `useState(defaultInvoiceId …)` отработал,
  // когда счёт ещё не был выбран, и застыл пустым: пользователь открывал конкретный счёт,
  // жал «Зафиксировать платёж» — и снова выбирал в списке тот же счёт руками. Синхронизируем
  // на КАЖДОМ открытии.
  useEffect(() => {
    if (!open) return;
    setInvoiceId(defaultInvoiceId ? String(defaultInvoiceId) : '');
  }, [open, defaultInvoiceId]);

  // Сумма по умолчанию — весь остаток к оплате (Stripe/Odoo/QuickBooks предлагают именно его:
  // полная оплата — самый частый случай, частичную пользователь исправит одним движением).
  // Только пока поле не тронуто, чтобы не затирать введённое вручную.
  const [amountTouched, setAmountTouched] = useState(false);
  useEffect(() => {
    if (!open) { setAmountTouched(false); return; }
    if (!amountTouched && balanceDue > 0) setAmount(balanceDueStr);
  }, [open, amountTouched, balanceDue, balanceDueStr]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!invoiceId) {
      toast.error(t('recordPayment.errors.invoiceRequired'));
      return;
    }
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) {
      toast.error(t('recordPayment.errors.amountInvalid'));
      return;
    }
    if (balanceDue > 0 && amt > balanceDue + 0.001) {
      toast.error(t('recordPayment.errors.amountExceedsBalance', { balance: balanceDueStr }));
      return;
    }
    try {
      await recordMut.mutateAsync({
        invoiceId: Number(invoiceId),
        amount: amount.trim(),
        paidAt,
        method,
        reference: reference.trim() || undefined,
        proofFile: proofFile ?? undefined,
      });
      toast.success(t('recordPayment.success'));
      onRecorded?.();
      onOpenChange(false);
      setInvoiceId(defaultInvoiceId ? String(defaultInvoiceId) : '');
      setAmount('');
      setReference('');
      setProofFile(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!recordMut.isPending) onOpenChange(v);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Wallet className="h-5 w-5" aria-hidden="true" />
              {t('recordPayment.title')}
            </DialogTitle>
            <DialogDescription>{t('recordPayment.description')}</DialogDescription>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <ManualModeBanner kind="payment" />
            <div className="space-y-1.5">
              <Label htmlFor="record-payment-invoice">
                {t('recordPayment.fields.invoice')}
              </Label>
              <Select
                value={invoiceId || undefined}
                onValueChange={(v) => {
                  setInvoiceId(v);
                  const inv = payableInvoices.find((i) => String(i.id) === v);
                  if (inv && !amount) setAmount(inv.balance_due);
                }}
                disabled={invoicesLoading || recordMut.isPending}
              >
                <SelectTrigger id="record-payment-invoice">
                  <SelectValue
                    placeholder={
                      invoicesLoading
                        ? t('common.loading')
                        : t('recordPayment.fields.invoicePlaceholder')
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {payableInvoices.length === 0 ? (
                    <div className="px-2 py-3 text-xs text-muted-foreground">
                      {t('recordPayment.noPayableInvoices')}
                    </div>
                  ) : (
                    payableInvoices.map((inv) => (
                      <SelectItem key={inv.id} value={String(inv.id)}>
                        {inv.number} · {inv.balance_due} · {t(`invoicesPage.status.${inv.status}`, inv.status)}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
              {selectedInvoice ? (
                <div className="text-xs text-muted-foreground">
                  {t('recordPayment.balanceDue', { value: selectedInvoice.balance_due })}
                </div>
              ) : null}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1.5">
                <Label htmlFor="record-payment-amount">
                  {t('recordPayment.fields.amount')}
                </Label>
                <Input
                  id="record-payment-amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={amount}
                  onChange={(e) => { setAmountTouched(true); setAmount(e.target.value); }}
                  placeholder="0.00"
                  inputMode="decimal"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="record-payment-date">
                  {t('recordPayment.fields.paidAt')}
                </Label>
                <Input
                  id="record-payment-date"
                  type="date"
                  value={paidAt}
                  onChange={(e) => setPaidAt(e.target.value)}
                  max={new Date().toISOString().slice(0, 10)}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="record-payment-method">
                {t('recordPayment.fields.method')}
              </Label>
              <Select value={method} onValueChange={(v) => setMethod(v as typeof method)}>
                <SelectTrigger id="record-payment-method">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {METHODS.map((m) => (
                    <SelectItem key={m} value={m}>
                      {t(`invoicesPage.method.${m}`, m)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="record-payment-ref">
                {t('recordPayment.fields.reference')}
              </Label>
              <Input
                id="record-payment-ref"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder={t('recordPayment.fields.referencePlaceholder')}
                maxLength={255}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="flex items-center gap-1 text-xs">
                <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                {t('recordPayment.fields.proof')}
              </Label>
              {proofFile ? (
                <div className="flex items-center justify-between rounded-md border p-2 text-xs">
                  <span className="truncate">{proofFile.name}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => setProofFile(null)}
                    aria-label={t('common.remove')}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                </div>
              ) : (
                <Input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png"
                  onChange={(e) => setProofFile(e.target.files?.[0] ?? null)}
                  className="text-xs"
                />
              )}
            </div>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={recordMut.isPending}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={recordMut.isPending}>
              {recordMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : null}
              {t('recordPayment.submit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
