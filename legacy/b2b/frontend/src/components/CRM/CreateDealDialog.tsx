import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2, Plus, Upload } from 'lucide-react';
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
import { Textarea } from '@/components/ui/textarea';
import { useCreateDeal } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';

interface CreateDealDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after the deal is created. Receives the new deal id so the caller
   *  can route to sourcing/import or the deal detail view. */
  onCreated?: (dealId: number) => void;
}

/**
 * BUYER "Create RFQ / procurement request" entry dialog.
 *
 * Creates a Deal in DRAFT and optionally hands the id back to the caller
 * for an Excel-import step. Keeps the form minimal — details are filled
 * on the deal detail page later.
 */
export function CreateDealDialog({ open, onOpenChange, onCreated }: CreateDealDialogProps) {
  const { t } = useTranslation();
  const [title, setTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [goToImport, setGoToImport] = useState(true);
  const createMut = useCreateDeal();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const cleanTitle = title.trim();
    if (!cleanTitle) {
      toast.error(t('createDeal.titleRequired'));
      return;
    }
    try {
      const deal = await createMut.mutateAsync({
        title: cleanTitle,
        notes: notes.trim() || undefined,
      });
      toast.success(t('createDeal.created'));
      onCreated?.(deal.id);
      onOpenChange(false);
      setTitle('');
      setNotes('');
      if (goToImport) {
        // Hash-based SPA navigation so this works inside AppShell context.
        window.location.hash = `sourcing-import?deal=${deal.id}`;
      }
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!createMut.isPending) onOpenChange(v);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{t('createDeal.title')}</DialogTitle>
            <DialogDescription>{t('createDeal.description')}</DialogDescription>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="new-deal-title">{t('createDeal.fields.title')}</Label>
              <Input
                id="new-deal-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('createDeal.fields.titlePlaceholder')}
                maxLength={255}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-deal-notes">{t('createDeal.fields.notes')}</Label>
              <Textarea
                id="new-deal-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t('createDeal.fields.notesPlaceholder')}
                rows={3}
                maxLength={2000}
              />
            </div>
            <label className="flex items-start gap-2 rounded-md border bg-muted/30 p-2 text-xs">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={goToImport}
                onChange={(e) => setGoToImport(e.target.checked)}
              />
              <span>
                <span className="flex items-center gap-1 font-medium">
                  <Upload className="h-3 w-3" aria-hidden="true" />
                  {t('createDeal.importOption')}
                </span>
                <span className="block text-muted-foreground">
                  {t('createDeal.importOptionHint')}
                </span>
              </span>
            </label>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={createMut.isPending}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={createMut.isPending}>
              {createMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="h-4 w-4" aria-hidden="true" />
              )}
              {t('createDeal.submit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
