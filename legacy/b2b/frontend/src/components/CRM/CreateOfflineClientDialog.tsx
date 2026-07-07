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
import { useCreateOfflineClient } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';

interface CreateOfflineClientDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * CRM Phase B — «Новый клиент»: the seller team records an OFFLINE client
 * (company + primary contact in one step). The backend de-dups by name/INN and
 * requires reachability (email OR phone) — mirrored here as a soft pre-check.
 */
export function CreateOfflineClientDialog({ open, onOpenChange }: CreateOfflineClientDialogProps) {
  const { t } = useTranslation();
  const [companyName, setCompanyName] = useState('');
  const [contactName, setContactName] = useState('');
  const [inn, setInn] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [position, setPosition] = useState('');
  const createMut = useCreateOfflineClient();

  const requiredFilled = companyName.trim().length > 0 && contactName.trim().length > 0;
  const hasReachability = email.trim().length > 0 || phone.trim().length > 0;
  const canSubmit = requiredFilled && hasReachability && !createMut.isPending;

  function resetForm() {
    setCompanyName('');
    setContactName('');
    setInn('');
    setEmail('');
    setPhone('');
    setPosition('');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    try {
      await createMut.mutateAsync({
        company_name: companyName.trim(),
        contact_name: contactName.trim(),
        inn: inn.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        position: position.trim() || undefined,
      });
      toast.success(t('counterparties.dialog.created'));
      onOpenChange(false);
      resetForm();
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
