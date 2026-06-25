import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Check, ChevronsUpDown, Loader2, Plus, Upload, X } from 'lucide-react';
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
import { Badge } from '@/components/ui/badge';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { useCreateDeal, useDealSuppliers, useRouteDeal } from '@/hooks/useCRM';
import { useUserStore } from '@/store/userStore';
import { translateApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

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
  // Optional multi-seller routing — buyer may target the RFQ at one or more
  // seller companies up front. Empty = unrouted (free-text заявка), still valid.
  const [sellerIds, setSellerIds] = useState<number[]>([]);
  const [sellerPickerOpen, setSellerPickerOpen] = useState(false);
  const createMut = useCreateDeal();
  const routeMut = useRouteDeal();

  // Routing is a buyer action — only show the picker on the buyer side.
  const activeStatus = useUserStore((s) => s.activeStatus);
  const isBuyerSide = activeStatus === 'BUYER';
  const { data: suppliers } = useDealSuppliers();

  const busy = createMut.isPending || routeMut.isPending;

  const toggleSeller = (id: number) =>
    setSellerIds((prev) => (prev.includes(id) ? prev.filter((existing) => existing !== id) : [...prev, id]));

  function resetForm() {
    setTitle('');
    setNotes('');
    setSellerIds([]);
  }

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
      // Route the fresh RFQ to the selected sellers BEFORE closing, if any were
      // picked. Routing is optional — an unrouted (free-text) заявка is fine.
      if (isBuyerSide && sellerIds.length > 0) {
        await routeMut.mutateAsync({ dealId: deal.id, sellerCompanyIds: sellerIds });
      }
      toast.success(t('createDeal.created'));
      // The caller routes to the request page, where the buyer adds items
      // manually OR via the inline "Upload file" (AI/template) — one screen.
      onCreated?.(deal.id);
      onOpenChange(false);
      resetForm();
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!busy) onOpenChange(v);
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
            {/* Optional multi-seller routing — buyer only. Empty = unrouted. */}
            {isBuyerSide && (suppliers?.length ?? 0) > 0 && (
              <div className="space-y-1.5">
                <Label htmlFor="new-deal-sellers">{t('createDeal.fields.routeToSellers')}</Label>
                <Popover open={sellerPickerOpen} onOpenChange={setSellerPickerOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      id="new-deal-sellers"
                      type="button"
                      variant="outline"
                      role="combobox"
                      aria-expanded={sellerPickerOpen}
                      className="w-full justify-between font-normal"
                      disabled={busy}
                    >
                      <span className={cn('truncate', sellerIds.length === 0 && 'text-muted-foreground')}>
                        {sellerIds.length === 0
                          ? t('createDeal.fields.routeToSellersPlaceholder')
                          : t('createDeal.fields.sellersSelected', { count: sellerIds.length })}
                      </span>
                      <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" aria-hidden="true" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
                    <Command>
                      <CommandInput placeholder={t('createDeal.fields.sellerSearchPlaceholder')} />
                      <CommandList>
                        <CommandEmpty>{t('createDeal.fields.noSellers')}</CommandEmpty>
                        <CommandGroup>
                          {(suppliers ?? []).map((seller) => {
                            const selected = sellerIds.includes(seller.id);
                            return (
                              <CommandItem
                                key={seller.id}
                                value={seller.name}
                                onSelect={() => toggleSeller(seller.id)}
                              >
                                <Check className={cn('mr-2 h-4 w-4', selected ? 'opacity-100' : 'opacity-0')} aria-hidden="true" />
                                <span className="truncate">{seller.name}</span>
                              </CommandItem>
                            );
                          })}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
                {sellerIds.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {(suppliers ?? [])
                      .filter((seller) => sellerIds.includes(seller.id))
                      .map((seller) => (
                        <Badge key={seller.id} variant="secondary" className="gap-1">
                          {seller.name}
                          <button
                            type="button"
                            className="-mr-0.5 rounded-sm hover:text-foreground"
                            onClick={() => toggleSeller(seller.id)}
                            aria-label={t('createDeal.fields.removeSeller', { name: seller.name })}
                            disabled={busy}
                          >
                            <X className="h-3 w-3" aria-hidden="true" />
                          </button>
                        </Badge>
                      ))}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">{t('createDeal.fields.routeToSellersHint')}</p>
              </div>
            )}
            <p className="flex items-center gap-1.5 rounded-md border border-border bg-muted/30 p-2 text-xs text-muted-foreground">
              <Upload className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {t('createDeal.importOptionHint')}
            </p>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? (
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
