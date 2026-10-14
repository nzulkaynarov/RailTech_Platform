/**
 * Invite-member form (workspace-role scoped by the active company context). Moved
 * verbatim from the former monolithic Cabinet/CompanyTeamSettings.tsx (spec PR 4
 * package split); logic unchanged.
 */
import { FormEvent, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { UserPlus, Loader2 } from 'lucide-react';

import { useInviteMember, useWorkspaceRoles } from '@/hooks/useAccounts';
import { workspaceRoleLabelKey } from '@/lib/codes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';

interface TeamInviteFormProps {
  companyId: number | null;
  /** Called after a successful invite (the parent refetches the team list). */
  onInvited: () => void;
}

export function TeamInviteForm({ companyId, onInvited }: TeamInviteFormProps) {
  const { t } = useTranslation();
  // Роли команды бэк-офиса: компания-владелец ERP — исполнитель (тип SUPPLIER в справочнике
  // ролей B2B). Покупательский набор ролей (CLIENT) ушёл вместе с контекстом покупателя
  // (M1-ERP-02 волна 3); собственный справочник ролей бэк-офиса — M1-ERP-05.
  const { data: workspaceRoles = [] } = useWorkspaceRoles('SUPPLIER');
  const inviteMut = useInviteMember();

  const availableWorkspaceRoles = useMemo(
    () => workspaceRoles.filter((r) => r.code !== 'OWNER'),
    [workspaceRoles],
  );
  const defaultWorkspaceRole = availableWorkspaceRoles[0]?.code ?? 'PROCUREMENT_MANAGER';

  const [email, setEmail] = useState('');
  // Роль — ПРОИЗВОДНОЕ значение: пока пользователь не выбрал свою, показываем дефолт из
  // подгруженного справочника. Раньше догоняющий `useMemo` дописывал состояние после загрузки
  // списка (побочный эффект в мемо, react-hooks/set-state-in-render); состояние здесь просто
  // не нужно — «ничего не выбрано» и есть корректное начальное значение.
  const [pickedRole, setPickedRole] = useState<string>('');
  const inviteRole = pickedRole || defaultWorkspaceRole;
  const setInviteRole = setPickedRole;

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    if (!companyId) return;
    try {
      await inviteMut.mutateAsync({ companyId, email, role: inviteRole });
      toast.success(t('team.inviteSuccess', { email }));
      setEmail('');
      onInvited();
    } catch (err) {
      type AxiosLike = { response?: { data?: { detail?: string; error?: string } } };
      const detail =
        (err as AxiosLike)?.response?.data?.detail ||
        (err as AxiosLike)?.response?.data?.error ||
        (err instanceof Error ? err.message : t('team.inviteError'));
      toast.error(String(detail));
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-muted/40 p-6">
      <h4 className="mb-4 flex items-center gap-2 text-base font-bold text-foreground">
        <UserPlus className="h-4 w-4 text-primary" aria-hidden="true" />
        {t('team.invite')}
      </h4>
      <form onSubmit={handleInvite} className="flex flex-col items-end gap-3 md:flex-row">
        <div className="w-full flex-1 space-y-1">
          <Label htmlFor="team-invite-email" className="sr-only">
            {t('team.emailPlaceholder')}
          </Label>
          <Input
            id="team-invite-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t('team.emailPlaceholder')}
            required
          />
        </div>
        <div className="w-full space-y-1 md:w-64">
          <Label htmlFor="team-invite-role" className="sr-only">
            {t('team.role')}
          </Label>
          <Select value={inviteRole} onValueChange={setInviteRole}>
            <SelectTrigger id="team-invite-role" className="w-full">
              <SelectValue placeholder={t('team.role')} />
            </SelectTrigger>
            <SelectContent>
              {availableWorkspaceRoles.map((r) => (
                <SelectItem key={r.code} value={r.code}>
                  {workspaceRoleLabelKey(r.code) ? t(workspaceRoleLabelKey(r.code)) : r.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          type="submit"
          disabled={inviteMut.isPending || !email}
          className="w-full md:w-auto"
        >
          {inviteMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : null}
          {t('common.send')}
        </Button>
      </form>
      <p className="mt-3 text-xs text-muted-foreground">{t('team.inviteHint')}</p>
    </div>
  );
}
