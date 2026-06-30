import { FormEvent, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Users,
  UserPlus,
  Shield,
  CheckCircle2,
  Loader2,
  Plus,
  Pencil,
  Trash2,
  Lock,
} from 'lucide-react';
import { useAuthStore } from '../../store/authStore';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { useUserStore } from '../../store/userStore';
import {
  useCompanyTeam,
  useInviteMember,
  useWorkspaceRoles,
  useCompanyRoles,
  useCreateCompanyRole,
  useUpdateCompanyRole,
  useDeleteCompanyRole,
  useAssignMemberRole,
  usePermissionCatalog,
} from '../../hooks/useAccounts';
import { CompanyRole } from '../../api/accountsApi';
import { workspaceRoleLabelKey } from '@/lib/codes';
import type { TFunction } from 'i18next';
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
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from '@/components/ui/sheet';
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

// ─── Error helpers ──────────────────────────────────────────────────────────

interface BackendErrorShape {
  response?: { data?: { error?: string; detail?: string } };
}

/** Backend service error codes → i18n message keys (see accounts/views/roles.py). */
const ROLE_ERROR_KEYS: Record<string, string> = {
  ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES: 'team.rolesSection.errors.onlyTeamManager',
  SYSTEM_ROLE_IMMUTABLE: 'team.rolesSection.errors.systemImmutable',
  ROLE_HAS_MEMBERS_REASSIGN_FIRST: 'team.rolesSection.errors.roleHasMembers',
  CANNOT_DEMOTE_LAST_COMPANY_ADMIN: 'team.rolesSection.errors.lastAdmin',
  MEMBER_NOT_FOUND: 'team.rolesSection.errors.memberNotFound',
  ROLE_NOT_FOUND: 'team.rolesSection.errors.roleNotFound',
  ROLE_NAME_REQUIRED: 'team.rolesSection.errors.nameRequired',
  ROLE_NAME_TAKEN: 'team.rolesSection.errors.nameTaken',
  UNKNOWN_PERMISSION_CODE: 'team.rolesSection.errors.unknownPermission',
  ROLE_COMPANY_MISMATCH: 'team.rolesSection.errors.companyMismatch',
};

/**
 * i18next uses '.' as its key separator, but permission codes contain dots
 * (e.g. "quote.build"). Map the dotted code to a single-segment key under
 * `permissions` so it resolves against the (nested) locale object.
 */
function permLabelKey(code: string): string {
  return `permissions.${code.replace(/\./g, '_')}`;
}

/** Resolve a thrown axios error to a localized, human-readable message. */
function resolveRoleError(err: unknown, translate: TFunction, fallbackKey: string): string {
  const data = (err as BackendErrorShape)?.response?.data;
  const code = data?.error;
  if (code && ROLE_ERROR_KEYS[code]) {
    return translate(ROLE_ERROR_KEYS[code]);
  }
  if (data?.detail) return data.detail;
  return translate(fallbackKey);
}

// ─── Role Editor Sheet ──────────────────────────────────────────────────────

interface RoleSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editingRole: CompanyRole | null;
}

function RoleEditorSheet({ open, onOpenChange, editingRole }: RoleSheetProps) {
  const { t } = useTranslation();
  const { data: permissionGroups = [] } = usePermissionCatalog();
  const createMut = useCreateCompanyRole();
  const updateMut = useUpdateCompanyRole();

  const isEdit = editingRole !== null;
  const isSystemRole = editingRole?.is_system ?? false;

  const [name, setName] = useState('');
  const [selectedPerms, setSelectedPerms] = useState<Set<string>>(new Set());

  // Sync state when sheet opens or editingRole changes
  useMemo(() => {
    if (open) {
      setName(editingRole?.name ?? '');
      setSelectedPerms(new Set(editingRole?.permissions ?? []));
    }
  }, [open, editingRole]);

  function togglePerm(code: string) {
    setSelectedPerms((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const permissions = Array.from(selectedPerms);
    try {
      if (isEdit && editingRole) {
        await updateMut.mutateAsync({ id: editingRole.id, data: { name, permissions } });
        toast.success(t('team.rolesSection.updateSuccess'));
      } else {
        await createMut.mutateAsync({ name, permissions });
        toast.success(t('team.rolesSection.createSuccess'));
      }
      onOpenChange(false);
    } catch (err) {
      toast.error(resolveRoleError(err, t, 'common.error'));
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader className="pb-4">
          <SheetTitle>
            {isEdit ? t('team.rolesSection.editRole') : t('team.rolesSection.addRole')}
          </SheetTitle>
        </SheetHeader>

        {isSystemRole ? (
          <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4 mx-4">
            <Lock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">{t('team.rolesSection.systemRoleReadonly')}</p>
          </div>
        ) : (
          <form id="role-editor-form" onSubmit={handleSubmit} className="px-4 space-y-6">
            <div className="space-y-1.5">
              <Label htmlFor="role-name">{t('team.rolesSection.roleName')}</Label>
              <Input
                id="role-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('team.rolesSection.roleNamePlaceholder')}
                required
              />
            </div>

            <div className="space-y-3">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">
                  {t('team.rolesSection.permissions')}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t('team.rolesSection.permissionsHint')}
                </p>
              </div>
              {permissionGroups.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
              ) : (
                <div className="space-y-5">
                  {permissionGroups.map((group) => {
                    const groupLabel =
                      t(`team.rolesSection.groups.${group.key}`, { defaultValue: group.label });
                    return (
                      <div key={group.key} className="space-y-2">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          {groupLabel}
                        </p>
                        <div className="grid grid-cols-1 gap-2">
                          {group.permissions.map((perm) => (
                            <label
                              key={perm.code}
                              htmlFor={`perm-${perm.code}`}
                              className="flex items-center gap-2.5 cursor-pointer rounded-lg border border-border px-3 py-2 hover:bg-muted/40 transition-colors"
                            >
                              <Checkbox
                                id={`perm-${perm.code}`}
                                checked={selectedPerms.has(perm.code)}
                                onCheckedChange={() => togglePerm(perm.code)}
                              />
                              <span className="text-sm text-foreground">{t(permLabelKey(perm.code), { defaultValue: perm.label })}</span>
                            </label>
                          ))}
                        </div>
                        <Separator />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </form>
        )}

        {!isSystemRole && (
          <SheetFooter className="gap-2 pt-4">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
              {t('common.cancel')}
            </Button>
            <Button
              type="submit"
              form="role-editor-form"
              disabled={isPending || !name.trim()}
            >
              {isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {t('team.rolesSection.saveRole')}
            </Button>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ─── Roles Section ─────────────────────────────────────────────────────────

function RolesSection() {
  const { t } = useTranslation();
  const { data: companyRoles = [], isLoading } = useCompanyRoles();
  const deleteMut = useDeleteCompanyRole();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<CompanyRole | null>(null);

  function openCreate() {
    setEditingRole(null);
    setSheetOpen(true);
  }

  function openEdit(role: CompanyRole) {
    setEditingRole(role);
    setSheetOpen(true);
  }

  async function handleDelete(role: CompanyRole) {
    try {
      await deleteMut.mutateAsync(role.id);
      toast.success(t('team.rolesSection.deleteSuccess'));
    } catch (err) {
      toast.error(resolveRoleError(err, t, 'team.rolesSection.deleteBlockedByMembers'));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="flex items-center gap-2 text-base font-bold text-foreground">
            <Shield className="h-4 w-4 text-primary" aria-hidden="true" />
            {t('team.rolesSection.title')}
          </h4>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {t('team.rolesSection.subtitle')}
          </p>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          {t('team.rolesSection.addRole')}
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
        </div>
      ) : companyRoles.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          {t('team.rolesSection.noRoles')}
        </p>
      ) : (
        <div className="rounded-2xl border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-b border-border bg-muted/50 text-xs">
                <TableHead className="p-4">{t('team.rolesSection.roleName')}</TableHead>
                <TableHead className="p-4">{t('team.rolesSection.permissions')}</TableHead>
                <TableHead className="p-4">{t('common.members', { defaultValue: '' })}</TableHead>
                <TableHead className="p-4 w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {companyRoles.map((role) => (
                <TableRow key={role.id} className="hover:bg-muted/40 transition-colors">
                  <TableCell className="p-4">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">{role.name}</span>
                      {role.is_system && (
                        <Badge variant="secondary" className="text-xs">
                          {t('team.rolesSection.systemBadge')}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="p-4">
                    {role.permissions.length === 0 ? (
                      <span className="text-xs text-muted-foreground">
                        {t('team.rolesSection.noPermissions')}
                      </span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {role.permissions.slice(0, 3).map((perm) => (
                          <Badge key={perm} variant="outline" className="text-xs font-normal">
                            {t(permLabelKey(perm), { defaultValue: perm })}
                          </Badge>
                        ))}
                        {role.permissions.length > 3 && (
                          <Badge variant="outline" className="text-xs font-normal">
                            +{role.permissions.length - 3}
                          </Badge>
                        )}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="p-4">
                    <span className="text-sm text-muted-foreground">
                      {t('team.rolesSection.memberCount', { count: role.member_count })}
                    </span>
                  </TableCell>
                  <TableCell className="p-4">
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => openEdit(role)}
                        aria-label={t('team.rolesSection.editRole')}
                      >
                        <Pencil className="h-4 w-4" aria-hidden="true" />
                      </Button>
                      {!role.is_system && (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-destructive hover:text-destructive"
                              aria-label={t('team.rolesSection.deleteRole')}
                              disabled={deleteMut.isPending}
                            >
                              <Trash2 className="h-4 w-4" aria-hidden="true" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                {t('team.rolesSection.deleteRole')}
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                {t('team.rolesSection.deleteConfirm', { name: role.name })}
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                              <AlertDialogAction
                                onClick={() => handleDelete(role)}
                                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                              >
                                {t('common.delete')}
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <RoleEditorSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        editingRole={editingRole}
      />
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function CompanyTeamSettings() {
  const { t } = useTranslation();
  const { user } = useAuthStore();
  const activeStatus = useUserStore((s) => s.activeStatus);

  // Map frontend CompanyStatus → backend CompanyType code for workspace-role filter
  const companyTypeForRoles =
    activeStatus === 'BUYER' ? 'CLIENT' : 'SUPPLIER';

  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  // U2: team management gated on the team.manage PERMISSION (delegated company admin), not OWNER.
  const canManageTeam = useHasCompanyPermission('team.manage');

  const { data: team = [], isLoading, refetch } = useCompanyTeam(companyId);
  const { data: companyRoles = [] } = useCompanyRoles(companyId ?? undefined);
  const { data: workspaceRoles = [] } = useWorkspaceRoles(companyTypeForRoles);
  const inviteMut = useInviteMember();
  const assignMut = useAssignMemberRole();

  const availableWorkspaceRoles = useMemo(
    () => workspaceRoles.filter((r) => r.code !== 'OWNER'),
    [workspaceRoles],
  );
  const defaultWorkspaceRole = availableWorkspaceRoles[0]?.code ?? 'PROCUREMENT_MANAGER';

  const [email, setEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<string>(defaultWorkspaceRole);

  // Keep the selected role in sync with the fetched list on first load
  useMemo(() => {
    if (!inviteRole && defaultWorkspaceRole) setInviteRole(defaultWorkspaceRole);
  }, [inviteRole, defaultWorkspaceRole]);

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    if (!companyId) return;
    try {
      await inviteMut.mutateAsync({ companyId, email, role: inviteRole });
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

  async function handleAssignCompanyRole(memberId: number, roleIdStr: string) {
    const roleId = parseInt(roleIdStr, 10);
    try {
      await assignMut.mutateAsync({ member_id: memberId, role_id: roleId });
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
      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-b border-border bg-muted/50 text-xs">
                <TableHead className="p-4">{t('team.employee')}</TableHead>
                <TableHead className="p-4">{t('team.companyRole')}</TableHead>
                <TableHead className="p-4">{t('team.status')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {team.map((member) => {
                type MemberExt = typeof member & {
                  membership_id?: number;
                  company_role?: number | null;
                };
                const extMember = member as MemberExt;
                const myMembership =
                  member.memberships?.find((m) => m.company === companyId) ??
                  member.memberships?.[0];
                const memberId = myMembership?.id ?? extMember.membership_id ?? extMember.id;
                const currentCompanyRoleId: number | null =
                  (myMembership as (typeof myMembership & { company_role?: number | null }) | undefined)
                    ?.company_role ?? extMember.company_role ?? null;
                const isSelf = member.id === user?.id;
                const canEdit = canManageTeam && !isSelf;

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
                      {canEdit && companyRoles.length > 0 ? (
                        <Select
                          value={currentCompanyRoleId !== null ? String(currentCompanyRoleId) : ''}
                          onValueChange={(val) => handleAssignCompanyRole(memberId, val)}
                          disabled={assignMut.isPending}
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
                      )}
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
                  <TableCell colSpan={3} className="p-8 text-center text-muted-foreground">
                    {t('team.noMembers')}
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* ── Invite form (owner only) ── */}
      {canManageTeam ? (
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
