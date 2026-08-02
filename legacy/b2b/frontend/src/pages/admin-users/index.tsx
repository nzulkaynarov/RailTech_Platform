import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Shield, Check, Pause, Pencil, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { formatDate } from '@/lib/formatLocale';
import { Button } from '@/components/ui/button';
import { AdminDataTable, useAdminTableQueryState } from '@/components/Admin/AdminDataTable';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useUsers, useSystemRoles, useDeleteUser } from '@/hooks/useAccounts';
import { PageShell, ErrorState } from '../shared/PageShell';
import { systemRoleLabelKey } from '@/lib/codes';
import type { User as UserType } from '@/api/accountsApi';
import { UserDetailSheet } from './UserDetailSheet';
import { CreateUserSheet } from './CreateUserSheet';

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
  const { data: users = [], isLoading, isError, refetch } = useUsers(queryParams);

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
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
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
            label: t(systemRoleLabelKey(r.code)),
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
                {u.role_data?.code ? t(systemRoleLabelKey(u.role_data.code)) : '—'}
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
                {u.last_login ? formatDate(u.last_login) : '—'}
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
      )}

      <UserDetailSheet
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
