import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { Plus, Trash2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { useSubmitBid } from '@/hooks/useBidding';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { sumMoney, lineTotal } from '@/utils/decimal';

interface BidItemDraft {
  description: string;
  quantity: string;
  unit_price: string;
  lead_time_days: string;
}

interface SupplierBidSubmitDialogProps {
  dealId: number | null;
  supplierId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Optional pre-fill items from the Deal's QuoteItems */
  suggestedItems?: Array<{ description: string; quantity: number }>;
}

function emptyItem(): BidItemDraft {
  return { description: '', quantity: '1', unit_price: '0', lead_time_days: '' };
}

export function SupplierBidSubmitDialog({
  dealId, supplierId, open, onOpenChange, suggestedItems,
}: SupplierBidSubmitDialogProps) {
  const { t } = useTranslation();
  const submitMut = useSubmitBid();
  const [items, setItems] = useState<BidItemDraft[]>(() =>
    suggestedItems?.length
      ? suggestedItems.map((i) => ({
          description: i.description,
          quantity: String(i.quantity),
          unit_price: '0',
          lead_time_days: '',
        }))
      : [emptyItem()]
  );
  const [notes, setNotes] = useState('');
  const [leadTime, setLeadTime] = useState('');

  const total = useMemo(
    () => sumMoney(items.map((it) => lineTotal(it.unit_price, Number(it.quantity) || 0))),
    [items],
  );

  const updateItem = (idx: number, patch: Partial<BidItemDraft>) => {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  };

  const addItem = () => setItems((prev) => [...prev, emptyItem()]);
  const removeItem = (idx: number) => setItems((prev) => prev.filter((_, i) => i !== idx));

  const submit = async () => {
    if (!dealId || !supplierId) return;
    const payloadItems = items
      .filter((it) => it.description.trim() && Number(it.unit_price) > 0)
      .map((it) => ({
        description: it.description.trim(),
        quantity: Number(it.quantity) || 1,
        unit_price: it.unit_price,
        lead_time_days: it.lead_time_days ? Number(it.lead_time_days) : null,
      }));
    if (!payloadItems.length) {
      toast.error(t('supplierBidsPage.emptyState'));
      return;
    }
    try {
      await submitMut.mutateAsync({
        deal_id: dealId,
        supplier_id: supplierId,
        items: payloadItems,
        notes,
        lead_time_days: leadTime ? Number(leadTime) : undefined,
      });
      toast.success(t('supplierBidsPage.submitted'));
      onOpenChange(false);
      setItems([emptyItem()]);
      setNotes('');
      setLeadTime('');
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('supplierBidsPage.submit')}</DialogTitle>
          <DialogDescription>
            {t('supplierBidsPage.table.deal')}: #{dealId}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <ManualModeBanner kind="payment" />

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead>Unit price</TableHead>
                <TableHead>{t('supplierBidsPage.table.leadTime')}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it, idx) => (
                <TableRow key={idx}>
                  <TableCell>{idx + 1}</TableCell>
                  <TableCell>
                    <Input
                      value={it.description}
                      onChange={(e) => updateItem(idx, { description: e.target.value })}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number" min="1"
                      value={it.quantity}
                      onChange={(e) => updateItem(idx, { quantity: e.target.value })}
                      className="w-20"
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number" step="0.01" min="0"
                      value={it.unit_price}
                      onChange={(e) => updateItem(idx, { unit_price: e.target.value })}
                      className="w-28"
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number" min="0"
                      value={it.lead_time_days}
                      onChange={(e) => updateItem(idx, { lead_time_days: e.target.value })}
                      className="w-20"
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost" size="sm"
                      onClick={() => removeItem(idx)}
                      disabled={items.length === 1}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <Button size="sm" variant="outline" onClick={addItem}>
            <Plus className="mr-2 h-4 w-4" />
            Item
          </Button>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="lt">{t('supplierBidsPage.table.leadTime')}</Label>
              <Input
                id="lt"
                type="number" min="0"
                value={leadTime}
                onChange={(e) => setLeadTime(e.target.value)}
              />
            </div>
            <div>
              <Label>{t('supplierBidsPage.table.total')}</Label>
              <p className="mt-2 text-lg font-bold tabular-nums">{total.toFixed(2)}</p>
            </div>
          </div>

          <div>
            <Label htmlFor="notes">Notes</Label>
            <Textarea
              id="notes" rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={submitMut.isPending || !dealId || !supplierId}>
            {t('supplierBidsPage.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
