/**
 * Company team members table — ResponsiveDataTable (repo convention; §2.4: data tables
 * are full width). Row-derivation logic moved verbatim from the former monolithic
 * Cabinet/CompanyTeamSettings.tsx (spec PR 4 package split).
 */
import { useTranslation } from 'react-i18next';
import { CheckCircle2 } from 'lucide-react';

import type { CompanyRole, User, UserMembership } from '@/api/accountsApi';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { Badge } from '@/components/ui/badge';
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
  return { member, memberId, currentCompanyRoleId, isSelf, canEdit: canManageTeam && !isSelf };
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
      header: t('team.status'),
      cell: () => (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
          <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          {t('team.active')}
        </span>
      ),
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
