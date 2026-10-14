/**
 * Team settings section — assembled from the Settings/team package (spec PR 4 split of the
 * former 685-line Cabinet/CompanyTeamSettings.tsx; behavior unchanged). §2.4: the members
 * table is data — full width, no reading cap.
 */
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Users, Shield, Loader2 } from 'lucide-react';

import { useAuthStore } from '@/store/authStore';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { useCompanyTeam, useCompanyRoles, useAssignMemberRoles } from '@/hooks/useAccounts';
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';

import { TeamMembersTable } from './TeamMembersTable';
import { TeamInviteForm } from './TeamInviteForm';
import { RolesSection } from './RolesSection';
import { resolveRoleError } from './roleErrors';

export function CompanyTeamSettings() {
  const { t } = useTranslation();
  const { user } = useAuthStore();

  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  // Управление командой — право роли `team.manage` (M1-ERP-05); администратор (is_superuser) — всё.
  const canManageTeam = useHasCompanyPermission('team.manage');

  const { data: team = [], isLoading, refetch } = useCompanyTeam(companyId);
  const { data: companyRoles = [] } = useCompanyRoles(companyId ?? undefined);
  const assignMut = useAssignMemberRoles();

  async function handleAssignRoles(memberId: number, roleIds: number[]) {
    try {
      await assignMut.mutateAsync({ member_id: memberId, role_ids: roleIds });
      toast.success(t('team.rolesSection.assignSuccess'));
    } catch (err) {
      toast.error(resolveRoleError(err, t, 'common.error'));
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
    <div className="space-y-8">
      {/* ── Section header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
            <Users className="h-5 w-5 text-primary" aria-hidden="true" />
            {t('team.title')}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{t('team.subtitle')}</p>
        </div>
      </div>

      {/* ── Members table ── */}
      <Card>
        <CardContent className="p-0">
          <TeamMembersTable
            team={team}
            companyId={companyId}
            companyRoles={companyRoles}
            canManageTeam={canManageTeam}
            currentUserId={user?.id}
            onAssignRoles={handleAssignRoles}
            assignPending={assignMut.isPending}
          />
        </CardContent>
      </Card>

      {/* ── Invite form (team.manage only) ── */}
      {canManageTeam ? (
        <TeamInviteForm companyId={companyId} onInvited={refetch} />
      ) : (
        <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
          <Shield className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium text-muted-foreground">{t('team.ownerOnly')}</p>
        </div>
      )}

      <Separator />

      {/* ── Roles section ── */}
      <RolesSection />
    </div>
  );
}

export default CompanyTeamSettings;
