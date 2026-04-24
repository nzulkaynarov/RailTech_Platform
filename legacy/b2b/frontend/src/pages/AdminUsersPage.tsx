import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Shield, Check, Pause,
  Mail, Phone, Building2, Calendar, User,
  Pencil, Trash2, Plus, AlertTriangle,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AdminDataTable, useAdminTableQueryState } from '@/components/Admin/AdminDataTable';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { DetailKPIGrid } from '@/components/Admin/DetailKPIGrid';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter,
} from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  useUsers, useToggleUserActive, useSystemRoles, useChangeUserRole,
  useCreateUser, useUpdateUser, useDeleteUser,
  useWorkspaceRoles, useAddUserMembership, useRemoveUserMembership,
  useCompanies, useUploadUserAvatar, useDeleteUserAvatar,
} from '@/hooks/useAccounts';
import { PageShell, EmptyState } from './shared/PageShell';
import type { User as UserType } from '@/api/accountsApi';
import { ImageUpload } from '@/components/Shared/ImageUpload';

type Draft = Partial<UserType>;

function MembershipsPanel({ user }: { user: UserType }) {
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
                  <p className="text-xs text-muted-foreground">{m.role_name ?? m.role_code ?? '—'}</p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemove(m.id)}
                  disabled={removeMut.isPending}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
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
                <SelectItem key={r.code} value={r.code}>{r.name}</SelectItem>
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

function DetailSheet({
  user, open, onOpenChange, onDeleteRequest,
}: {
  user: UserType | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleteRequest: (u: UserType) => void;
}) {
  const { t } = useTranslation();
  const { data: roles } = useSystemRoles();
  const toggleMut = useToggleUserActive();
  const changeRoleMut = useChangeUserRole();
  const updateMut = useUpdateUser();
  const uploadAvatarMut = useUploadUserAvatar();
  const deleteAvatarMut = useDeleteUserAvatar();

  const [draft, setDraft] = useState<Draft>(() => user ?? {});
  const [roleCode, setRoleCode] = useState<string>('');

  useEffect(() => {
    if (user) {
      setDraft({ ...user });
      setRoleCode(user.role_code ?? user.role_data?.code ?? '');
    }
  }, [user]);

  if (!user) return null;

  const busy = toggleMut.isPending || changeRoleMut.isPending || updateMut.isPending;
  const memberships = user.memberships ?? [];
  const hasMemberships = memberships.length > 0;
  // ADMIN можно назначить только юзеру без memberships (см. services.change_user_role).
  const adminDisabledReason = hasMemberships ? t('pages.adminUsers.errors.ADMIN_ROLE_REQUIRES_NO_MEMBERSHIPS') : '';

  const infoRows = [
    { icon: Mail, value: user.email },
    ...(user.phone ? [{ icon: Phone, value: user.phone }] : []),
    { icon: Calendar, value: user.date_joined ? new Date(user.date_joined).toLocaleDateString() : '—' },
  ];

  const handleToggleActive = async () => {
    try {
      await toggleMut.mutateAsync(user.id);
      toast.success(
        user.is_active
          ? t('pages.adminUsers.deactivated', { name: user.email })
          : t('pages.adminUsers.activated', { name: user.email })
      );
    } catch {
      toast.error(t('common.error'));
    }
  };

  const handleSave = async () => {
    try {
      const prevRole = user.role_code ?? user.role_data?.code;
      if (roleCode && roleCode !== prevRole) {
        await changeRoleMut.mutateAsync({ id: user.id, role: roleCode });
      }
      await updateMut.mutateAsync({
        id: user.id,
        data: {
          first_name: draft.first_name,
          last_name: draft.last_name,
          phone: draft.phone,
        },
      });
      toast.success(t('pages.adminUsers.saved'));
      onOpenChange(false);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? t(`pages.adminUsers.errors.${detail}`, detail) : t('pages.adminUsers.saveFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <User className="h-5 w-5" />
            {user.first_name || user.last_name
              ? `${user.first_name} ${user.last_name}`.trim()
              : user.email}
          </SheetTitle>
          <SheetDescription>{user.email}</SheetDescription>
        </SheetHeader>

        <div className="mt-4 px-4">
          <Tabs defaultValue="profile">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="profile" className="text-xs">{t('pages.adminUsers.tabs.profile')}</TabsTrigger>
              <TabsTrigger value="role" className="text-xs">{t('pages.adminUsers.tabs.role')}</TabsTrigger>
              <TabsTrigger value="memberships" className="text-xs">
                {t('pages.adminUsers.tabs.memberships')}
                {hasMemberships && <Badge variant="outline" className="ml-1.5 text-[10px]">{memberships.length}</Badge>}
              </TabsTrigger>
              <TabsTrigger value="timeline" className="text-xs">
                {t('platformAdmin.activity.title')}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="profile" className="mt-4 space-y-4">
              <DetailKPIGrid
                columns={4}
                items={[
                  {
                    label: t('pages.adminUsers.statusLabel.active'),
                    value: user.is_active
                      ? t('pages.adminUsers.statusLabel.active')
                      : t('pages.adminUsers.statusLabel.inactive'),
                    icon: user.is_active ? <Check className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />,
                    tone: user.is_active ? 'success' : 'warning',
                  },
                  {
                    label: t('pages.adminUsers.table.role'),
                    value: user.role_data?.name ?? '—',
                  },
                  {
                    label: t('pages.adminUsers.tabs.memberships'),
                    value: String(memberships.length),
                  },
                  {
                    label: t('pages.adminUsers.table.lastLogin'),
                    value: user.last_login
                      ? new Date(user.last_login).toLocaleDateString()
                      : '—',
                    hint: user.date_joined
                      ? t('pages.adminUsers.joinedHint', {
                          date: new Date(user.date_joined).toLocaleDateString(),
                        })
                      : undefined,
                  },
                ]}
              />
              <ImageUpload
                value={user.avatar ?? null}
                onUpload={async (file) => {
                  await uploadAvatarMut.mutateAsync({ userId: user.id, file });
                }}
                onRemove={async () => {
                  await deleteAvatarMut.mutateAsync(user.id);
                }}
                fallback={((user.first_name?.[0] || '') + (user.last_name?.[0] || '')).toUpperCase() || user.email.slice(0, 2).toUpperCase()}
                shape="circle"
                label={t('profile.personalInfo.avatar')}
              />
              <div className="rounded-lg border p-3 space-y-2.5">
                {infoRows.map((r, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <r.icon className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="text-sm">{r.value}</span>
                  </div>
                ))}
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
                <div className="space-y-2 col-span-2">
                  <Label>{t('pages.adminUsers.fields.phone')}</Label>
                  <Input value={draft.phone ?? ''} onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))} />
                </div>
              </div>

              <div className="flex items-center justify-between rounded-lg border p-3">
                <span className="text-sm text-muted-foreground">{t('pages.adminUsers.table.status')}</span>
                <div className="flex items-center gap-3">
                  <span className={`text-sm font-medium ${user.is_active ? 'text-success' : 'text-destructive'}`}>
                    {user.is_active ? t('pages.adminUsers.statusLabel.active') : t('pages.adminUsers.statusLabel.inactive')}
                  </span>
                  <Switch checked={user.is_active} onCheckedChange={handleToggleActive} disabled={busy} />
                </div>
              </div>
              {user.last_login && (
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{t('pages.adminUsers.detail.lastLogin')}</span>
                  <span className="tabular-nums">{new Date(user.last_login).toLocaleString()}</span>
                </div>
              )}
            </TabsContent>

            <TabsContent value="role" className="mt-4 space-y-4">
              <div className="rounded-lg border border-info/40 bg-info/5 p-3 text-xs text-muted-foreground">
                {t('pages.adminUsers.roleTab.explanation')}
              </div>

              <div className="space-y-2">
                <Label>{t('pages.adminUsers.roleTab.systemRole')}</Label>
                <Select value={roleCode || undefined} onValueChange={setRoleCode}>
                  <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {(roles ?? []).map((r) => {
                      const adminBlocked = r.code === 'ADMIN' && hasMemberships;
                      return (
                        <SelectItem key={r.code} value={r.code} disabled={adminBlocked}>
                          {r.name}
                          {adminBlocked && (
                            <span className="text-xs text-muted-foreground ml-2">
                              · {t('pages.adminUsers.roleTab.blockedByMembership')}
                            </span>
                          )}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                {adminDisabledReason && (
                  <p className="flex items-center gap-1.5 text-xs text-warning">
                    <AlertTriangle className="h-3 w-3" />
                    {adminDisabledReason}
                  </p>
                )}
              </div>
            </TabsContent>

            <TabsContent value="memberships" className="mt-4">
              <MembershipsPanel user={user} />
            </TabsContent>

            <TabsContent value="timeline" className="mt-4">
              <AdminActivityTimeline entityType="user" entityId={user.id} />
            </TabsContent>
          </Tabs>
        </div>

        <SheetFooter className="mt-6 flex flex-col gap-2 sm:flex-col">
          <Button onClick={handleSave} disabled={busy} className="w-full">
            {t('pages.adminUsers.save')}
          </Button>
          <Button
            variant="destructive"
            onClick={() => onDeleteRequest(user)}
            disabled={busy}
            className="w-full gap-2"
          >
            <Trash2 className="h-3.5 w-3.5" />
            {t('pages.adminUsers.delete')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function CreateUserSheet({
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
                  <SelectItem key={r.code} value={r.code}>{r.name}</SelectItem>
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

const STORAGE_KEY = 'adminUsers';

export function AdminUsersPage() {
  const { t } = useTranslation();
  const { data: roles } = useSystemRoles();
  const deleteMut = useDeleteUser();

  const [detailTarget, setDetailTarget] = useState<UserType | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserType | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const tableState = useAdminTableQueryState(STORAGE_KEY);
  const queryParams = useMemo(() => {
    const p: Record<string, string | boolean> = {};
    if (tableState.search) p.search = tableState.search;
    const tab = tableState.tab || 'all';
    if (tab === 'active') p.is_active = true;
    else if (tab === 'inactive') p.is_active = false;
    else if (tab.startsWith('role:')) p['role__code'] = tab.slice(5);
    return Object.keys(p).length ? p : undefined;
  }, [tableState.search, tableState.tab]);

  const { data: allUsers = [] } = useUsers();
  const { data: users = [], isLoading } = useUsers(queryParams);

  const selectedUser = useMemo(() => {
    if (!detailTarget) return null;
    return allUsers.find((u) => u.id === detailTarget.id) ?? detailTarget;
  }, [allUsers, detailTarget]);

  const filtered = users;

  const counts = useMemo(() => ({
    all: allUsers.length,
    active: allUsers.filter((u) => u.is_active).length,
    inactive: allUsers.filter((u) => !u.is_active).length,
    admin: allUsers.filter((u) => u.role_data?.code === 'ADMIN').length,
  }), [allUsers]);

  const stats = [
    { label: t('pages.adminUsers.stats.total'), value: String(counts.all) },
    { label: t('pages.adminUsers.stats.active'), value: String(counts.active) },
    { label: t('pages.adminUsers.stats.staff'), value: String(counts.admin) },
    { label: t('pages.adminUsers.stats.inactive'), value: String(counts.inactive) },
  ];

  const onDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('pages.adminUsers.deleted'));
      setDeleteTarget(null);
      setDetailTarget(null);
    } catch {
      toast.error(t('pages.adminUsers.deleteFailed'));
    }
  };

  return (
    <PageShell
      title={t('pages.adminUsers.title')}
      description={t('pages.adminUsers.description')}
      icon={<Shield className="h-5 w-5" />}
      stats={stats}
    >
      <AdminDataTable<UserType>
        storageKey={STORAGE_KEY}
        rows={filtered}
        getRowId={(u) => u.id}
        isLoading={isLoading}
        onRowClick={(u) => setDetailTarget(u)}
        searchPlaceholder={t('pages.adminUsers.searchPlaceholder')}
        exportUrl={`${window.location.origin}/api/v1/accounts/users/export/`}
        primaryAction={
          <Button size="sm" className="h-8 text-xs" onClick={() => setCreateOpen(true)}>
            {t('pages.adminUsers.newUser')}
          </Button>
        }
        tabs={[
          { id: 'all', label: t('common.all'), count: counts.all },
          { id: 'active', label: t('pages.adminUsers.statusLabel.active'), count: counts.active },
          { id: 'inactive', label: t('pages.adminUsers.statusLabel.inactive'), count: counts.inactive },
          ...(roles?.map((r) => ({
            id: `role:${r.code}`,
            label: r.name,
          })) ?? []),
        ]}
        columns={[
          {
            id: 'name',
            header: t('pages.adminUsers.table.name'),
            cell: (u) => (
              <span className="font-medium">
                {u.first_name || u.last_name ? `${u.first_name ?? ''} ${u.last_name ?? ''}`.trim() : '—'}
              </span>
            ),
            alwaysVisible: true,
          },
          {
            id: 'email',
            header: t('pages.adminUsers.table.email'),
            cell: (u) => <span className="text-muted-foreground">{u.email}</span>,
          },
          {
            id: 'role',
            header: t('pages.adminUsers.table.role'),
            cell: (u) => (
              <Badge variant={u.role_data?.code === 'ADMIN' ? 'default' : 'outline'}>
                {u.role_data?.name ?? '—'}
              </Badge>
            ),
          },
          {
            id: 'status',
            header: t('pages.adminUsers.table.status'),
            cell: (u) => (
              <Badge variant={u.is_active ? 'default' : 'secondary'} className="gap-1">
                {u.is_active ? (
                  <>
                    <Check className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.active')}
                  </>
                ) : (
                  <>
                    <Pause className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.inactive')}
                  </>
                )}
              </Badge>
            ),
          },
          {
            id: 'lastLogin',
            header: t('pages.adminUsers.table.lastLogin'),
            cell: (u) => (
              <span className="text-muted-foreground">
                {u.last_login ? new Date(u.last_login).toLocaleDateString() : '—'}
              </span>
            ),
          },
        ]}
        rowActions={[
          {
            id: 'edit',
            label: t('common.open'),
            icon: <Pencil className="h-3.5 w-3.5" />,
            onRun: (u) => setDetailTarget(u),
          },
          {
            id: 'delete',
            label: t('pages.adminUsers.delete'),
            icon: <Trash2 className="h-3.5 w-3.5" />,
            variant: 'destructive',
            onRun: (u) => setDeleteTarget(u),
          },
        ]}
        emptyIcon={<Shield className="h-5 w-5 text-muted-foreground" />}
        emptyTitle={t('pages.common.noData')}
      />

      <DetailSheet
        user={selectedUser}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
        onDeleteRequest={(u) => setDeleteTarget(u)}
      />

      <CreateUserSheet open={createOpen} onOpenChange={setCreateOpen} />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('pages.adminUsers.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('pages.adminUsers.confirmDeleteDesc', { email: deleteTarget?.email })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('pages.adminUsers.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={deleteMut.isPending}>
              {t('pages.adminUsers.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default AdminUsersPage;
