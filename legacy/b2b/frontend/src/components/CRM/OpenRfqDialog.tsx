import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useOpenRfq } from '@/hooks/useBidding';
import { useCompanies } from '@/hooks/useAccounts';

interface OpenRfqDialogProps {
  dealId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function OpenRfqDialog({ dealId, open, onOpenChange }: OpenRfqDialogProps) {
  const { t } = useTranslation();
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const { data: companies } = useCompanies({ types__code: 'SUPPLIER' });
  const openMut = useOpenRfq();

  const toggle = (id: number) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelectedIds(next);
  };

  const submit = async () => {
    if (!dealId) return;
    try {
      await openMut.mutateAsync({
        dealId,
        supplierIds: selectedIds.size > 0 ? Array.from(selectedIds) : undefined,
      });
      toast.success(t('rfqDialog.opened'));
      onOpenChange(false);
      setSelectedIds(new Set());
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('rfqDialog.title')}</DialogTitle>
          <DialogDescription>{t('rfqDialog.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Label>{t('rfqDialog.selectSuppliers')}</Label>
          <ScrollArea className="h-64 rounded-md border p-3">
            <div className="space-y-2">
              {(companies ?? []).map((c) => (
                <div key={c.id} className="flex items-center gap-2">
                  <Checkbox
                    id={`sup-${c.id}`}
                    checked={selectedIds.has(c.id)}
                    onCheckedChange={() => toggle(c.id)}
                  />
                  <label htmlFor={`sup-${c.id}`} className="cursor-pointer text-sm">
                    {c.name} <span className="text-muted-foreground">· {c.inn}</span>
                  </label>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={openMut.isPending || !dealId}>
            {t('rfqDialog.open')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
