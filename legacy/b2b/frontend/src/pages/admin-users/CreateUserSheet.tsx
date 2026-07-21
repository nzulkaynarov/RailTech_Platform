import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter,
} from '@/components/ui/sheet';
import { useSystemRoles, useCreateUser } from '@/hooks/useAccounts';
import { systemRoleLabelKey } from '@/lib/codes';
import type { Draft } from './types';

export function CreateUserSheet({
  open, onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const { data: roles } = useSystemRoles();
  const createMut = useCreateUser();

  const [draft, setDraft] = useState<Draft>({ email: '', first_name: '', last_name: '', phone: '' });
  const [roleCode, setRoleCode] = useState<string>('');

  const submit = async () => {
    if (!draft.email?.trim()) {
      toast.error(t('pages.adminUsers.emailRequired'));
      return;
    }
    try {
      await createMut.mutateAsync({
        email: draft.email,
        first_name: draft.first_name,
        last_name: draft.last_name,
        phone: draft.phone,
        role: roleCode || undefined,
      });
      toast.success(t('pages.adminUsers.created'));
      onOpenChange(false);
      setDraft({ email: '', first_name: '', last_name: '', phone: '' });
      setRoleCode('');
    } catch {
      toast.error(t('pages.adminUsers.createFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{t('pages.adminUsers.newUser')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="space-y-2">
            <Label>{t('pages.adminUsers.fields.email')}</Label>
            <Input type="email" value={draft.email ?? ''} onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('pages.adminUsers.fields.firstName')}</Label>
              <Input value={draft.first_name ?? ''} onChange={(e) => setDraft((d) => ({ ...d, first_name: e.target.value }))} />
            </div>
            <div className="space-y-2">
              <Label>{t('pages.adminUsers.fields.lastName')}</Label>
              <Input value={draft.last_name ?? ''} onChange={(e) => setDraft((d) => ({ ...d, last_name: e.target.value }))} />
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('pages.adminUsers.fields.phone')}</Label>
            <Input value={draft.phone ?? ''} onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))} />
          </div>
          <div className="space-y-2">
            <Label>{t('pages.adminUsers.table.role')}</Label>
            <Select value={roleCode || undefined} onValueChange={setRoleCode}>
              <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {(roles ?? []).map((r) => (
                  // Localize the SystemRole by CODE, matching how the same roles are
                  // rendered in the table (lines ~340 / ~705) — the DB `name` is RU-only.
                  <SelectItem key={r.code} value={r.code}>{t(systemRoleLabelKey(r.code))}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={createMut.isPending} className="w-full">
            {t('pages.adminUsers.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
