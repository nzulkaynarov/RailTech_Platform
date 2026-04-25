import { FormEvent, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Users,
  UserPlus,
  Shield,
  CheckCircle2,
  Loader2,
  ShoppingBag,
  Wallet,
} from 'lucide-react';
import { useAuthStore } from '../../store/authStore';
import { useUserStore } from '../../store/userStore';
import {
  useCompanyTeam,
  useInviteMember,
  useUpdateMemberCapabilities,
  useWorkspaceRoles,
} from '../../hooks/useAccounts';
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';

export function CompanyTeamSettings() {
  const { t } = useTranslation();
  const { user } = useAuthStore();
  const activeStatus = useUserStore((s) => s.activeStatus);

  // Map frontend CompanyStatus → backend CompanyType code for workspace-role filter
  const companyTypeForRoles =
    activeStatus === 'BUYER'
      ? 'CLIENT'
      : activeStatus === 'SELLER'
        ? 'SUPPLIER'
        : 'MANUFACTURER';

  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  const isOwner = user?.workspace_role === 'OWNER';

  const { data: team = [], isLoading, refetch } = useCompanyTeam(companyId);
  const { data: workspaceRoles = [] } = useWorkspaceRoles(companyTypeForRoles);
  const inviteMut = useInviteMember();
  const capMut = useUpdateMemberCapabilities();

  const availableRoles = useMemo(
    () => workspaceRoles.filter((r) => r.code !== 'OWNER'),
    [workspaceRoles],
  );
  const defaultRole = availableRoles[0]?.code ?? 'PROCUREMENT_MANAGER';

  const [email, setEmail] = useState('');
  const [role, setRole] = useState<string>(defaultRole);

  // Keep the selected role in sync with the fetched list on first load.
  useMemo(() => {
    if (!role && defaultRole) setRole(defaultRole);
  }, [role, defaultRole]);

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    if (!companyId) return;
    try {
      await inviteMut.mutateAsync({ companyId, email, role });
      toast.success(t('team.inviteSuccess', { email }));
      setEmail('');
      refetch();
    } catch (err) {
      type AxiosLike = { response?: { data?: { detail?: string; error?: string } } };
      const detail =
        (err as AxiosLike)?.response?.data?.detail ||
        (err as AxiosLike)?.response?.data?.error ||
        (err instanceof Error ? err.message : t('team.inviteError'));
      toast.error(String(detail));
    }
  }

  async function toggleCapability(
    memberId: number,
    field: 'can_sell' | 'can_buy',
    value: boolean,
  ) {
    if (!companyId) return;
    try {
      await capMut.mutateAsync({
        companyId,
        member_id: memberId,
        [field]: value,
      } as Parameters<typeof capMut.mutateAsync>[0]);
      toast.success(t('team.capabilityUpdated'));
    } catch (err) {
      type AxiosLike = { response?: { data?: { detail?: string } } };
      toast.error(
        (err as AxiosLike)?.response?.data?.detail ??
          (err instanceof Error ? err.message : t('team.inviteError')),
      );
    }
  }

  if (isLoading) {
    return (
      <div className="flex p-10 justify-center" role="status">
        <Loader2 className="h-8 w-8 text-muted-foreground animate-spin" aria-hidden="true" />
        <span className="sr-only">{t('common.loading')}</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
            <Users className="h-5 w-5 text-primary" aria-hidden="true" />
            {t('team.title')}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{t('team.subtitle')}</p>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-b border-border bg-muted/50 text-xs">
                <TableHead className="p-4">{t('team.employee')}</TableHead>
                <TableHead className="p-4">{t('team.role')}</TableHead>
                <TableHead className="p-4 text-center">
                  <span className="inline-flex items-center gap-1">
                    <Wallet className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('team.capabilities.canBuy')}
                  </span>
                </TableHead>
                <TableHead className="p-4 text-center">
                  <span className="inline-flex items-center gap-1">
                    <ShoppingBag className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('team.capabilities.canSell')}
                  </span>
                </TableHead>
                <TableHead className="p-4">{t('team.status')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {team.map((member) => {
                type MemberExt = typeof member & {
                  membership_id?: number;
                  workspace_role_name?: string;
                };
                const extMember = member as MemberExt;
                // Prefer the CompanyMember.id exposed by the team serializer.
                // Fall back to user.id when the backend hasn't provided it yet.
                const memberId = extMember.membership_id ?? extMember.id;
                const canBuy = extMember.can_buy ?? false;
                const canSell = extMember.can_sell ?? false;
                const isSelf = member.id === user?.id;
                const canEdit = isOwner && !isSelf;
                return (
                  <TableRow key={memberId} className="transition-colors hover:bg-muted/40">
                    <TableCell className="p-4">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-sm font-semibold uppercase text-muted-foreground">
                          {member.email.charAt(0)}
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-foreground">
                            {member.first_name || member.username}
                            {isSelf ? (
                              <span className="ml-2 text-xs font-normal text-muted-foreground">
                                {t('team.itsYou')}
                              </span>
                            ) : null}
                          </div>
                          <div className="text-xs text-muted-foreground">{member.email}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="p-4">
                      <Badge variant={member.workspace_role === 'OWNER' ? 'default' : 'outline'}>
                        {extMember.workspace_role_name
                          ?? (member.workspace_role ? t(`team.roles.${member.workspace_role}`, member.workspace_role) : t('team.employee'))}
                      </Badge>
                    </TableCell>
                    <TableCell className="p-4 text-center">
                      <Switch
                        checked={canBuy}
                        disabled={!canEdit || capMut.isPending}
                        onCheckedChange={(v) => toggleCapability(memberId, 'can_buy', v)}
                        aria-label={t('team.capabilities.canBuy')}
                      />
                    </TableCell>
                    <TableCell className="p-4 text-center">
                      <Switch
                        checked={canSell}
                        disabled={!canEdit || capMut.isPending}
                        onCheckedChange={(v) => toggleCapability(memberId, 'can_sell', v)}
                        aria-label={t('team.capabilities.canSell')}
                      />
                    </TableCell>
                    <TableCell className="p-4">
                      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
                        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                        {t('team.active')}
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
              {team.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="p-8 text-center text-muted-foreground">
                    {t('team.noMembers')}
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </div>

      {isOwner ? (
        <div className="rounded-2xl border border-border bg-muted/40 p-6">
          <h4 className="mb-4 flex items-center gap-2 text-base font-bold text-foreground">
            <UserPlus className="h-4 w-4 text-primary" aria-hidden="true" />
            {t('team.invite')}
          </h4>
          <form
            onSubmit={handleInvite}
            className="flex flex-col items-end gap-3 md:flex-row"
          >
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
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger id="team-invite-role" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {availableRoles.map((r) => (
                    <SelectItem key={r.code} value={r.code}>
                      {r.name}
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
      ) : (
        <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
          <Shield className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium text-muted-foreground">{t('team.ownerOnly')}</p>
        </div>
      )}
    </div>
  );
}

export default CompanyTeamSettings;
