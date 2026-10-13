import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { useMatchCandidates, useReassignProduct } from '@/hooks/useCRM';

interface ReassignProductDialogProps {
  quoteItemId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ReassignProductDialog({
  quoteItemId, open, onOpenChange,
}: ReassignProductDialogProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useMatchCandidates(open ? quoteItemId : null);
  const reassign = useReassignProduct();

  const onPick = async (productId: number | null) => {
    if (!quoteItemId) return;
    try {
      await reassign.mutateAsync({ quoteItemId, productId });
      toast.success(t('rematchDialog.assigned'));
      onOpenChange(false);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('rematchDialog.title')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label>{t('rematchDialog.rawLabel')}</Label>
            <p className="text-sm">{data?.raw ?? '—'}</p>
          </div>
          <div>
            <Label>{t('rematchDialog.candidatesLabel')}</Label>
            {isLoading ? (
              <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
            ) : (data?.candidates?.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">{t('rematchDialog.noCandidates')}</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('rematchDialog.columns.sku')}</TableHead>
                    <TableHead>{t('rematchDialog.columns.name')}</TableHead>
                    <TableHead>{t('rematchDialog.columns.gost')}</TableHead>
                    <TableHead>{t('rematchDialog.columns.score')}</TableHead>
                    <TableHead className="text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data?.candidates ?? []).map((c) => (
                    <TableRow key={c.product_id}>
                      <TableCell className="font-mono text-xs">{c.sku}</TableCell>
                      <TableCell>{c.name}</TableCell>
                      <TableCell className="text-xs">{c.gost || '—'}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{c.score}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          onClick={() => onPick(c.product_id)}
                          disabled={reassign.isPending}
                        >
                          {t('rematchDialog.apply')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onPick(null)} disabled={reassign.isPending}>
            {t('rematchDialog.clear')}
          </Button>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
