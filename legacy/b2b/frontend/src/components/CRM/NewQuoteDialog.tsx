import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Calculator, Check, ChevronsUpDown, Loader2, UserPlus, Users } from 'lucide-react';
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
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { CreateOfflineClientDialog } from './CreateOfflineClientDialog';
import { useContacts, useCreateDeal } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';
import type { Contact } from '@/api/crmApi';

interface NewQuoteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Receives the id of the deal to open the КП builder on. */
  onCreated: (dealId: number) => void;
}

/** Which recipient the seller is quoting. */
type RecipientMode = 'book' | 'new' | 'none';

/**
 * Wave E F2 — the SELLER's «Новый КП» entry point.
 *
 * A seller starts from the offer, not from a buyer's заявка: pick a counterparty from
 * the client book, record a brand-new offline client inline, or price something with no
 * client at all («калькулятор» draft, F3). All three create a Deal the seller owns —
 * server-side that ownership is a DealSellerRouting row (F1) — and drop straight into
 * the КП builder. A client-less draft cannot be SENT until a recipient exists
 * (backend answers RECIPIENT_REQUIRED).
 */
export function NewQuoteDialog({ open, onOpenChange, onCreated }: NewQuoteDialogProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<RecipientMode>('book');
  const [title, setTitle] = useState('');
  const [contactId, setContactId] = useState<number | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [createClientOpen, setCreateClientOpen] = useState(false);
  const createDeal = useCreateDeal();
  const { data: contacts, isLoading: contactsLoading } = useContacts();

  const contactList = contacts ?? [];
  const selectedContact = contactList.find((c) => c.id === contactId) ?? null;
  const busy = createDeal.isPending;
  const canSubmit = !busy && (mode !== 'book' || contactId !== null);

  function resetForm() {
    setMode('book');
    setTitle('');
    setContactId(null);
  }

  /** One creation path for all three modes — only the recipient payload differs. */
  async function createFor(payload: { contact_id?: number; without_client?: boolean }) {
    const deal = await createDeal.mutateAsync({
      title: title.trim() || t('newQuote.defaultTitle'),
      ...payload,
    });
    toast.success(t('newQuote.created'));
    onOpenChange(false);
    resetForm();
    onCreated(deal.id);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    if (mode === 'new') {
      setCreateClientOpen(true);
      return;
    }
    try {
      await createFor(mode === 'book' ? { contact_id: contactId! } : { without_client: true });
    } catch (error) {
      toast.error(translateApiError(error));
    }
  }

  /** The inline «new client» flow returns the fresh contact — quote it right away. */
  async function handleClientCreated(contact: Contact) {
    try {
      await createFor({ contact_id: contact.id });
    } catch (error) {
      toast.error(translateApiError(error));
    }
  }

  const contactLabel = (contact: Contact) =>
    contact.company_name ? `${contact.company_name} — ${contact.name}` : contact.name;

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!busy) onOpenChange(next);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <form onSubmit={submit}>
            <DialogHeader>
              <DialogTitle>{t('newQuote.title')}</DialogTitle>
              <DialogDescription>{t('newQuote.description')}</DialogDescription>
            </DialogHeader>

            <div className="mt-3 space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="new-quote-title">{t('newQuote.fields.title')}</Label>
                <Input
                  id="new-quote-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={t('newQuote.fields.titlePlaceholder')}
                  maxLength={255}
                  autoFocus
                />
              </div>

              <div className="space-y-2">
                <Label>{t('newQuote.fields.recipient')}</Label>
                <RadioGroup
                  value={mode}
                  onValueChange={(next) => setMode(next as RecipientMode)}
                  className="gap-2"
                  disabled={busy}
                >
                  <div className="flex items-start gap-2 rounded-md border border-border p-2.5">
                    <RadioGroupItem value="book" id="new-quote-mode-book" className="mt-0.5" />
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <Label htmlFor="new-quote-mode-book" className="flex items-center gap-1.5 font-medium">
                        <Users className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        {t('newQuote.modes.book')}
                      </Label>
                      {mode === 'book' && (
                        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                          <PopoverTrigger asChild>
                            <Button
                              type="button"
                              variant="outline"
                              role="combobox"
                              aria-expanded={pickerOpen}
                              className="w-full justify-between font-normal"
                              disabled={busy}
                            >
                              <span className={cn('truncate', !selectedContact && 'text-muted-foreground')}>
                                {selectedContact
                                  ? contactLabel(selectedContact)
                                  : t('newQuote.fields.pickContactPlaceholder')}
                              </span>
                              <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" aria-hidden="true" />
                            </Button>
                          </PopoverTrigger>
                          <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
                            <Command>
                              <CommandInput placeholder={t('newQuote.fields.contactSearchPlaceholder')} />
                              <CommandList>
                                <CommandEmpty>
                                  {contactsLoading ? t('common.loading') : t('newQuote.fields.noContacts')}
                                </CommandEmpty>
                                <CommandGroup>
                                  {contactList.map((contact) => (
                                    <CommandItem
                                      key={contact.id}
                                      value={contactLabel(contact)}
                                      onSelect={() => {
                                        setContactId(contact.id);
                                        setPickerOpen(false);
                                      }}
                                    >
                                      <Check
                                        className={cn(
                                          'mr-2 h-4 w-4',
                                          contact.id === contactId ? 'opacity-100' : 'opacity-0',
                                        )}
                                        aria-hidden="true"
                                      />
                                      <span className="truncate">{contactLabel(contact)}</span>
                                    </CommandItem>
                                  ))}
                                </CommandGroup>
                              </CommandList>
                            </Command>
                          </PopoverContent>
                        </Popover>
                      )}
                    </div>
                  </div>

                  <div className="flex items-start gap-2 rounded-md border border-border p-2.5">
                    <RadioGroupItem value="new" id="new-quote-mode-new" className="mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <Label htmlFor="new-quote-mode-new" className="flex items-center gap-1.5 font-medium">
                        <UserPlus className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        {t('newQuote.modes.new')}
                      </Label>
                      <p className="mt-0.5 text-xs text-muted-foreground">{t('newQuote.modes.newHint')}</p>
                    </div>
                  </div>

                  <div className="flex items-start gap-2 rounded-md border border-border p-2.5">
                    <RadioGroupItem value="none" id="new-quote-mode-none" className="mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <Label htmlFor="new-quote-mode-none" className="flex items-center gap-1.5 font-medium">
                        <Calculator className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        {t('newQuote.modes.none')}
                      </Label>
                      <p className="mt-0.5 text-xs text-muted-foreground">{t('newQuote.modes.noneHint')}</p>
                    </div>
                  </div>
                </RadioGroup>
              </div>
            </div>

            <DialogFooter className="mt-4 gap-2">
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={!canSubmit}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                {mode === 'new' ? t('newQuote.submitNewClient') : t('newQuote.submit')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <CreateOfflineClientDialog
        open={createClientOpen}
        onOpenChange={setCreateClientOpen}
        onCreated={handleClientCreated}
      />
    </>
  );
}
