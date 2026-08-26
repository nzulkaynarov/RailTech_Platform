import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Building2, Trash2, Plus, AlertTriangle } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  useWorkspaceRoles, useAddUserMembership, useRemoveUserMembership, useCompanies,
} from '@/hooks/useAccounts';
import { EmptyState } from '../shared/PageShell';
import { workspaceRoleLabelKey } from '@/lib/codes';
import type { User as UserType } from '@/api/accountsApi';

export function MembershipsPanel({ user }: { user: UserType }) {
  const { t } = useTranslation();
  const { data: companies } = useCompanies();
  const addMut = useAddUserMembership();
  const removeMut = useRemoveUserMembership();

  const [draftCompanyId, setDraftCompanyId] = useState<string>('');
  const [draftRoleCode, setDraftRoleCode] = useState<string>('');
  const [draftIsPrimary, setDraftIsPrimary] = useState(false);

  const selectedCompany = useMemo(
    () => (companies ?? []).find((c) => String(c.id) === draftCompanyId),
    [companies, draftCompanyId],
  );
  const companyTypeForRoles = selectedCompany?.company_types?.[0];
  const { data: workspaceRoles } = useWorkspaceRoles(companyTypeForRoles);

  const memberships = user.memberships ?? [];
  const hasMemberships = memberships.length > 0;
  const isPlatformAdminUser = user.role_code === 'ADMIN' || user.role_data?.code === 'ADMIN';

  const handleAdd = async () => {
    if (!draftCompanyId || !draftRoleCode) {
      toast.error(t('pages.adminUsers.memberships.companyAndRoleRequired'));
      return;
    }
    try {
      await addMut.mutateAsync({
        userId: user.id,
        company: Number(draftCompanyId),
        workspaceRole: draftRoleCode,
        isPrimary: draftIsPrimary,
      });
      toast.success(t('pages.adminUsers.memberships.added'));
      setDraftCompanyId('');
      setDraftRoleCode('');
      setDraftIsPrimary(false);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? t(`pages.adminUsers.errors.${detail}`, detail) : t('pages.adminUsers.memberships.addFailed'));
    }
  };

  const handleRemove = async (membershipId: number) => {
    try {
      await removeMut.mutateAsync({ userId: user.id, membershipId });
      toast.success(t('pages.adminUsers.memberships.removed'));
    } catch {
      toast.error(t('pages.adminUsers.memberships.removeFailed'));
    }
  };

  if (isPlatformAdminUser) {
    return (
      <div className="rounded-lg border border-dashed p-4 text-center">
        <AlertTriangle className="h-5 w-5 mx-auto text-warning mb-2" />
        <p className="text-sm font-medium">{t('pages.adminUsers.memberships.platformAdminTitle')}</p>
        <p className="text-xs text-muted-foreground mt-1">{t('pages.adminUsers.memberships.platformAdminDesc')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-sm font-semibold mb-2">{t('pages.adminUsers.memberships.existing')}</h4>
        {!hasMemberships ? (
          <EmptyState icon={<Building2 className="h-5 w-5" />} message={t('pages.adminUsers.memberships.empty')} />
        ) : (
          <div className="space-y-2">
            {memberships.map((m) => (
              <div key={m.id} className="flex items-center justify-between rounded-lg border p-3 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium truncate">{m.company_name ?? `#${m.company}`}</span>
                    {m.is_primary && <Badge variant="outline" className="text-xs">{t('pages.adminUsers.memberships.primary')}</Badge>}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {workspaceRoleLabelKey(m.role_code)
                      ? t(workspaceRoleLabelKey(m.role_code))
                      : (m.role_name ?? m.role_code ?? '—')}
                  </p>
                </div>
                {/* Исключение человека из компании — необратимое действие с последствием для
                    ДРУГОГО человека: он теряет доступ к данным арендатора. Кнопка вызывала
                    мутацию напрямую, с одного клика, и не имела доступного имени — только
                    иконка. На соседних действиях того же экрана диалог уже стоял. */}
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('pages.adminUsers.memberships.remove')}
                      title={t('pages.adminUsers.memberships.remove')}
                      disabled={removeMut.isPending}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>{t('pages.adminUsers.memberships.removeConfirmTitle')}</AlertDialogTitle>
                      <AlertDialogDescription>
                        {t('pages.adminUsers.memberships.removeConfirmDesc', { company: m.company_name })}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                      <AlertDialogAction onClick={() => handleRemove(m.id)}>
                        {t('pages.adminUsers.memberships.remove')}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ))}
          </div>
        )}
      </div>

      <Separator />

      <div className="space-y-3 rounded-lg border p-3">
        <h4 className="text-sm font-semibold">{t('pages.adminUsers.memberships.addNew')}</h4>
        <div className="space-y-2">
          <Label>{t('pages.adminUsers.memberships.company')}</Label>
          <Select value={draftCompanyId || undefined} onValueChange={(v) => { setDraftCompanyId(v); setDraftRoleCode(''); }}>
            <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {(companies ?? []).map((c) => (
                <SelectItem key={c.id} value={String(c.id)}>
                  {c.name} {(c.company_types ?? []).length > 0 && (
                    <span className="text-xs text-muted-foreground ml-1">({(c.company_types ?? []).join(', ')})</span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>{t('pages.adminUsers.memberships.workspaceRole')}</Label>
          <Select value={draftRoleCode || undefined} onValueChange={setDraftRoleCode} disabled={!draftCompanyId}>
            <SelectTrigger><SelectValue placeholder={draftCompanyId ? '—' : t('pages.adminUsers.memberships.selectCompanyFirst')} /></SelectTrigger>
            <SelectContent>
              {(workspaceRoles ?? []).map((r) => (
                <SelectItem key={r.code} value={r.code}>
                  {workspaceRoleLabelKey(r.code) ? t(workspaceRoleLabelKey(r.code)) : r.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center justify-between">
          <Label className="text-sm font-normal">{t('pages.adminUsers.memberships.setPrimary')}</Label>
          <Switch checked={draftIsPrimary} onCheckedChange={setDraftIsPrimary} />
        </div>
        <Button onClick={handleAdd} disabled={addMut.isPending || !draftCompanyId || !draftRoleCode} className="w-full gap-2">
          <Plus className="h-4 w-4" />
          {t('pages.adminUsers.memberships.add')}
        </Button>
      </div>
    </div>
  );
}
