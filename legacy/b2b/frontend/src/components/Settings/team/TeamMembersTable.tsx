/**
 * Company team members table — ResponsiveDataTable (repo convention; §2.4: data tables
 * are full width). Row-derivation logic moved verbatim from the former monolithic
 * Cabinet/CompanyTeamSettings.tsx (spec PR 4 package split).
 *
 * S3 (spec P2/P8): a member with team.manage can deactivate/reactivate and remove OTHER
 * members (confirmed via AlertDialog); the Status column reads the member's REAL
 * `is_active`, not a hardcoded green «Active» badge. Never-orphan / self-guard errors
 * come from the backend and surface via translateApiError.
 */
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CheckCircle2, XCircle, UserCheck, UserX, Trash2 } from 'lucide-react';

import type { CompanyRole, User, UserMembership } from '@/api/accountsApi';
import { useRemoveMember, useToggleMemberActive } from '@/hooks/useAccounts';
import { translateApiError } from '@/lib/apiError';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';

interface TeamMembersTableProps {
  team: User[];
  companyId: number | null;
  companyRoles: CompanyRole[];
  /** team.manage permission (U2 — delegated company admin, not OWNER-only). */
  canManageTeam: boolean;
  currentUserId: number | undefined;
  onAssignRole: (memberId: number, roleIdStr: string) => void;
  assignPending: boolean;
}

/** Per-row derived data — same resolution rules as the pre-split component. */
interface MemberRow {
  member: User;
  memberId: number;
  currentCompanyRoleId: number | null;
  isSelf: boolean;
  canEdit: boolean;
  /** Real membership/account status (P8) — false for invited-but-not-activated / disabled. */
  isActive: boolean;
  displayName: string;
}

type MemberExt = User & { membership_id?: number; company_role?: number | null };

function toMemberRow(
  member: User,
  companyId: number | null,
  canManageTeam: boolean,
  currentUserId: number | undefined,
): MemberRow {
  const extMember = member as MemberExt;
  const myMembership =
    member.memberships?.find((m) => m.company === companyId) ?? member.memberships?.[0];
  const memberId = myMembership?.id ?? extMember.membership_id ?? extMember.id;
  const currentCompanyRoleId: number | null =
    (myMembership as (UserMembership & { company_role?: number | null }) | undefined)
      ?.company_role ?? extMember.company_role ?? null;
  const isSelf = member.id === currentUserId;
  // Real status (P8): the account-level is_active the backend returns per member.
  // Absent (older payloads) → treat as active so we never show a false «disabled».
  const isActive = member.is_active !== false;
  return {
    member,
    memberId,
    currentCompanyRoleId,
    isSelf,
    canEdit: canManageTeam && !isSelf,
    isActive,
    displayName: member.first_name || member.username || member.email,
  };
}

/** Deactivate/activate + remove actions for one member (team.manage, non-self). */
function MemberRowActions({
  companyId,
  memberId,
  displayName,
  isActive,
}: {
  companyId: number;
  memberId: number;
  displayName: string;
  isActive: boolean;
}) {
  const { t } = useTranslation();
  const toggleMut = useToggleMemberActive();
  const removeMut = useRemoveMember();

  async function handleToggle() {
    try {
      const res = await toggleMut.mutateAsync({ companyId, memberId });
      toast.success(res.is_active ? t('team.activateSuccess') : t('team.deactivateSuccess'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  }

  async function handleRemove() {
    try {
      await removeMut.mutateAsync({ companyId, memberId });
      toast.success(t('team.removeSuccess'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  }

  const busy = toggleMut.isPending || removeMut.isPending;

  return (
    <div className="flex items-center justify-end gap-1">
      {/* ── Deactivate / activate ── */}
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            aria-label={isActive ? t('team.deactivate') : t('team.activate')}
            disabled={busy}
          >
            {isActive ? (
              <UserX className="h-4 w-4" aria-hidden="true" />
            ) : (
              <UserCheck className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {isActive ? t('team.deactivate') : t('team.activate')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {isActive
                ? t('team.deactivateConfirm', { name: displayName })
                : t('team.activateConfirm', { name: displayName })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleToggle} disabled={busy}>
              {isActive ? t('team.deactivate') : t('team.activate')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── Remove from team ── */}
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-destructive hover:text-destructive"
            aria-label={t('team.remove')}
            disabled={busy}
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('team.remove')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('team.removeConfirm', { name: displayName })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRemove}
              disabled={busy}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t('team.remove')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export function TeamMembersTable({
  team, companyId, companyRoles, canManageTeam, currentUserId, onAssignRole, assignPending,
}: TeamMembersTableProps) {
  const { t } = useTranslation();

  if (team.length === 0) {
    return (
      <p className="p-8 text-center text-sm text-muted-foreground">{t('team.noMembers')}</p>
    );
  }

  const rows = team.map((member) => toMemberRow(member, companyId, canManageTeam, currentUserId));

  const columns: ResponsiveColumn<MemberRow>[] = [
    {
      id: 'employee',
      header: t('team.employee'),
      mobileTitle: true,
      cell: ({ member, isSelf }) => (
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
      ),
    },
    {
      id: 'companyRole',
      header: t('team.companyRole'),
      cell: ({ memberId, currentCompanyRoleId, canEdit }) =>
        canEdit && companyRoles.length > 0 ? (
          <Select
            value={currentCompanyRoleId !== null ? String(currentCompanyRoleId) : ''}
            onValueChange={(val) => onAssignRole(memberId, val)}
            disabled={assignPending}
          >
            <SelectTrigger className="w-52" aria-label={t('team.companyRole')}>
              <SelectValue placeholder={t('team.noRole')} />
            </SelectTrigger>
            <SelectContent>
              {companyRoles.map((cr) => (
                <SelectItem key={cr.id} value={String(cr.id)}>
                  {cr.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Badge variant="outline">
            {currentCompanyRoleId
              ? (companyRoles.find((cr) => cr.id === currentCompanyRoleId)?.name ??
                t('team.companyRole'))
              : t('team.noRole')}
          </Badge>
        ),
    },
    {
      id: 'status',
      header: t('team.status.label'),
      cell: ({ isActive }) =>
        isActive ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            {t('team.status.active')}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <XCircle className="h-4 w-4" aria-hidden="true" />
            {t('team.status.inactive')}
          </span>
        ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ memberId, canEdit, isActive, displayName }) =>
        canEdit && companyId ? (
          <MemberRowActions
            companyId={companyId}
            memberId={memberId}
            displayName={displayName}
            isActive={isActive}
          />
        ) : null,
    },
  ];

  return (
    <ResponsiveDataTable
      columns={columns}
      rows={rows}
      getRowId={(row) => row.memberId}
    />
  );
}
