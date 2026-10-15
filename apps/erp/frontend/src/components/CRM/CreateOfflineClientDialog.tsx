import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2, UserPlus } from 'lucide-react';
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
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCreateOfflineClient } from '@/hooks/useCRM';
import type { Contact } from '@/api/crmApi';
import { translateApiError } from '@/lib/apiError';

interface CreateOfflineClientDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Wave E F2 — the created contact, so a caller (e.g. «Новый КП») can immediately
   *  open a deal for it. Optional: the counterparties page ignores it. */
  onCreated?: (contact: Contact) => void;
}

/**
 * CRM Phase B — «Новый клиент»: the seller team records an OFFLINE client
 * (company + primary contact in one step). The backend de-dups by name/INN and
 * requires reachability (email OR phone) — mirrored here as a soft pre-check.
 */
export function CreateOfflineClientDialog({ open, onOpenChange, onCreated }: CreateOfflineClientDialogProps) {
  const { t } = useTranslation();
  const [companyName, setCompanyName] = useState('');
  const [contactName, setContactName] = useState('');
  const [inn, setInn] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [position, setPosition] = useState('');
  const [telegramUsername, setTelegramUsername] = useState('');
  const [canAct, setCanAct] = useState(true);
  const [preferredChannel, setPreferredChannel] = useState<'email' | 'telegram' | 'both'>('email');
  const createMut = useCreateOfflineClient();

  const requiredFilled = companyName.trim().length > 0 && contactName.trim().length > 0;
  const hasReachability = email.trim().length > 0 || phone.trim().length > 0 || telegramUsername.trim().length > 0;
  const canSubmit = requiredFilled && hasReachability && !createMut.isPending;

  function resetForm() {
    setCompanyName('');
    setContactName('');
    setInn('');
    setEmail('');
    setPhone('');
    setPosition('');
    setTelegramUsername('');
    setCanAct(true);
    setPreferredChannel('email');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    try {
      const contact = await createMut.mutateAsync({
        company_name: companyName.trim(),
        contact_name: contactName.trim(),
        inn: inn.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        position: position.trim() || undefined,
        telegram_username: telegramUsername.trim().replace(/^@/, '') || undefined,
        can_act: canAct,
        preferred_channel: preferredChannel,
      });
      toast.success(t('counterparties.dialog.created'));
      onOpenChange(false);
      resetForm();
      onCreated?.(contact);
    } catch (err) {
      toast.error(translateApiError(err));
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
            <DialogTitle>{t('counterparties.dialog.title')}</DialogTitle>
            <DialogDescription>{t('counterparties.dialog.description')}</DialogDescription>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="offline-client-company">{t('counterparties.dialog.companyName')} *</Label>
              <Input
                id="offline-client-company"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                maxLength={255}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="offline-client-contact">{t('counterparties.dialog.contactName')} *</Label>
              <Input
                id="offline-client-contact"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                maxLength={255}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="offline-client-inn">{t('counterparties.dialog.inn')}</Label>
              <Input
                id="offline-client-inn"
                value={inn}
                onChange={(e) => setInn(e.target.value)}
                maxLength={20}
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="offline-client-email">{t('counterparties.dialog.email')}</Label>
                <Input
                  id="offline-client-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  maxLength={254}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="offline-client-phone">{t('counterparties.dialog.phone')}</Label>
                <Input
                  id="offline-client-phone"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  maxLength={50}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="offline-client-position">{t('counterparties.dialog.position')}</Label>
              <Input
                id="offline-client-position"
                value={position}
                onChange={(e) => setPosition(e.target.value)}
                maxLength={255}
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="offline-client-telegram">{t('counterparties.dialog.telegramUsername')}</Label>
                <Input
                  id="offline-client-telegram"
                  placeholder="@username"
                  value={telegramUsername}
                  onChange={(e) => setTelegramUsername(e.target.value)}
                  maxLength={100}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="offline-client-channel">{t('counterparties.dialog.channel')}</Label>
                <Select
                  value={preferredChannel}
                  onValueChange={(v: 'email' | 'telegram' | 'both') => setPreferredChannel(v)}
                >
                  <SelectTrigger id="offline-client-channel" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="email">{t('counterparties.dialog.channelEmail')}</SelectItem>
                    <SelectItem value="telegram">{t('counterparties.dialog.channelTelegram')}</SelectItem>
                    <SelectItem value="both">{t('counterparties.dialog.channelBoth')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex items-center space-x-2 pt-1">
              <Checkbox
                id="offline-client-can-act"
                checked={canAct}
                onCheckedChange={(checked) => setCanAct(!!checked)}
              />
              <Label
                htmlFor="offline-client-can-act"
                className="text-sm font-normal cursor-pointer"
              >
                {t('counterparties.dialog.canAct')}
              </Label>
            </div>
            {!canSubmit && !createMut.isPending && (
              <p className="text-xs text-muted-foreground">{t('counterparties.dialog.hint')}</p>
            )}
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
            <Button type="submit" disabled={!canSubmit}>
              {createMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <UserPlus className="h-4 w-4" aria-hidden="true" />
              )}
              {t('counterparties.dialog.submit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
