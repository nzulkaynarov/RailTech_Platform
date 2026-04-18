import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Shield, Check, Pause,
  Mail, Phone, Building2, Calendar, User,
  Pencil, Trash2,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHeader, TableRow,
} from '@/components/ui/table';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
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
} from '@/hooks/useAccounts';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { User as UserType } from '@/api/accountsApi';

type Draft = Partial<UserType>;

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

  const infoRows = [
    { icon: Mail, value: user.email },
    ...(user.phone ? [{ icon: Phone, value: user.phone }] : []),
    ...(user.company?.name ? [{ icon: Building2, value: user.company.name }] : []),
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
      if (roleCode && roleCode !== (user.role_code ?? user.role_data?.code)) {
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
    } catch {
      toast.error(t('pages.adminUsers.saveFailed'));
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

        <div className="mt-2 space-y-6 px-4">
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('pages.adminUsers.detail.info')}</h3>
            <div className="rounded-lg border p-3 space-y-2.5">
              {infoRows.map((r, i) => (
                <div key={i} className="flex items-center gap-3">
                  <r.icon className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="text-sm">{r.value}</span>
                </div>
              ))}
            </div>
          </section>

          <Separator />

          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('pages.adminUsers.detail.editPersonal')}</h3>
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
          </section>

          <Separator />

          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('pages.adminUsers.detail.access')}</h3>

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

            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('pages.adminUsers.table.status')}</span>
              <div className="flex items-center gap-3">
                <span className={`text-sm font-medium ${user.is_active ? 'text-success' : 'text-destructive'}`}>
                  {user.is_active ? t('pages.adminUsers.statusLabel.active') : t('pages.adminUsers.statusLabel.inactive')}
                </span>
                <Switch checked={user.is_active} onCheckedChange={handleToggleActive} disabled={busy} />
              </div>
            </div>

            {user.last_login && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{t('pages.adminUsers.detail.lastLogin')}</span>
                <span className="text-sm tabular-nums">
                  {new Date(user.last_login).toLocaleString()}
                </span>
              </div>
            )}
          </section>
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

export function AdminUsersPage() {
  const { t } = useTranslation();
  const { data: users, isLoading } = useUsers();
  const { data: roles } = useSystemRoles();
  const deleteMut = useDeleteUser();

  const [detailTarget, setDetailTarget] = useState<UserType | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserType | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const params = useListParams(['role', 'status'] as const, { defaultOrdering: '-date_joined' });

  const selectedUser = useMemo(() => {
    if (!detailTarget || !users) return null;
    return users.find((u) => u.id === detailTarget.id) ?? detailTarget;
  }, [users, detailTarget]);

  const { items: pageItems, total } = useMemo(() => applyListParams(users ?? [], params, {
    searchFields: (u: UserType) => [u.email, u.first_name, u.last_name, u.phone, String(u.id)],
    filterPredicates: {
      role: (u, v) => (u.role_code ?? u.role_data?.code ?? '') === v,
      status: (u, v) => (v === 'active' ? !!u.is_active : !u.is_active),
    },
    sortAccessors: {
      email: (u) => u.email,
      name: (u) => `${u.last_name ?? ''} ${u.first_name ?? ''}`,
      date_joined: (u) => u.date_joined ?? '',
      last_login: (u) => u.last_login ?? '',
    },
  }), [users, params.search, params.filters, params.ordering, params.page, params.pageSize]);

  const stats = [
    { label: t('pages.adminUsers.stats.total'), value: String(users?.length ?? '—') },
    { label: t('pages.adminUsers.stats.active'), value: String(users?.filter((u) => u.is_active).length ?? '—') },
    { label: t('pages.adminUsers.stats.staff'), value: String(users?.filter((u) => u.role_data?.is_staff_level).length ?? '—') },
    { label: t('pages.adminUsers.stats.inactive'), value: String(users?.filter((u) => !u.is_active).length ?? '—') },
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
      <Toolbar
        searchValue={params.searchInput}
        onSearchChange={params.setSearchInput}
        searchPlaceholder={t('pages.adminUsers.searchPlaceholder')}
        filters={[
          {
            key: 'role',
            value: params.filters.role,
            onChange: (v) => params.setFilter('role', v),
            allLabel: t('pages.adminUsers.allRoles'),
            options: (roles ?? []).map((r) => ({ value: r.code, label: r.name })),
          },
          {
            key: 'status',
            value: params.filters.status,
            onChange: (v) => params.setFilter('status', v),
            allLabel: t('pages.adminUsers.allStatuses'),
            options: [
              { value: 'active', label: t('pages.adminUsers.statusLabel.active') },
              { value: 'inactive', label: t('pages.adminUsers.statusLabel.inactive') },
            ],
          },
        ]}
        newLabel={t('pages.adminUsers.newUser')}
        onNew={() => setCreateOpen(true)}
      />

      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !pageItems.length ? (
            <EmptyState icon={<Shield className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="name" current={params.ordering} onChange={params.toggleOrdering}>
                    {t('pages.adminUsers.table.name')}
                  </SortableHead>
                  <SortableHead sortKey="email" current={params.ordering} onChange={params.toggleOrdering}>
                    {t('pages.adminUsers.table.email')}
                  </SortableHead>
                  <SortableHead sortKey="role" current={params.ordering} onChange={params.toggleOrdering}>
                    {t('pages.adminUsers.table.role')}
                  </SortableHead>
                  <SortableHead sortKey="status" current={params.ordering} onChange={params.toggleOrdering}>
                    {t('pages.adminUsers.table.status')}
                  </SortableHead>
                  <SortableHead sortKey="last_login" current={params.ordering} onChange={params.toggleOrdering}>
                    {t('pages.adminUsers.table.lastLogin')}
                  </SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}} className="text-right">
                    {t('pages.adminUsers.table.actions')}
                  </SortableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((user) => (
                  <TableRow
                    key={user.id}
                    className="cursor-pointer"
                    onClick={() => setDetailTarget(user)}
                  >
                    <TableCell><span className="font-medium">{user.first_name} {user.last_name}</span></TableCell>
                    <TableCell className="text-muted-foreground">{user.email}</TableCell>
                    <TableCell>
                      <Badge variant={user.role_data?.is_staff_level ? 'default' : 'outline'}>
                        {user.role_data?.name ?? '—'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? 'default' : 'secondary'} className="gap-1">
                        {user.is_active
                          ? <><Check className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.active')}</>
                          : <><Pause className="h-3 w-3" /> {t('pages.adminUsers.statusLabel.inactive')}</>}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {user.last_login ? new Date(user.last_login).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        <Button variant="ghost" size="sm" onClick={() => setDetailTarget(user)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(user)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <Pager page={params.page} pageSize={params.pageSize} total={total} onPageChange={params.setPage} />
        </CardContent>
      </Card>

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
