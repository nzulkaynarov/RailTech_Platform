/**
 * Роли бэк-офиса (M1-ERP-05): системные шаблоны (BUSINESS §11 — имя по коду, только просмотр) и
 * свои роли компании; создание и правка — у сотрудника с `team.manage`.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Shield, Loader2, Plus, Pencil, Trash2, Eye } from 'lucide-react';

import { useCompanyRoles, useDeleteCompanyRole } from '@/hooks/useAccounts';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import type { CompanyRole } from '@/api/accountsApi';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
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

import { RoleEditorSheet } from './RoleEditorSheet';
import { permLabelKey, resolveRoleError, roleDisplayName } from './roleErrors';

export function RolesSection() {
  const { t } = useTranslation();
  const { data: companyRoles = [], isLoading } = useCompanyRoles();
  const deleteMut = useDeleteCompanyRole();
  const canManage = useHasCompanyPermission('team.manage');

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

  const columns: ResponsiveColumn<CompanyRole>[] = [
    {
      id: 'name',
      header: t('team.rolesSection.roleName'),
      mobileTitle: true,
      cell: (role) => (
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{roleDisplayName(role, t)}</span>
          {role.is_system && (
            <Badge variant="secondary" className="text-xs">
              {t('team.rolesSection.systemBadge')}
            </Badge>
          )}
        </div>
      ),
    },
    {
      id: 'permissions',
      header: t('team.rolesSection.permissions'),
      cell: (role) =>
        role.permissions.length === 0 ? (
          <span className="text-xs text-muted-foreground">
            {t('team.rolesSection.noPermissions')}
          </span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {role.permissions.slice(0, 3).map((perm) => (
              <Badge key={perm} variant="outline" className="max-w-full truncate text-xs font-normal">
                {t(permLabelKey(perm), { defaultValue: perm })}
              </Badge>
            ))}
            {role.permissions.length > 3 && (
              <Badge variant="outline" className="text-xs font-normal">
                +{role.permissions.length - 3}
              </Badge>
            )}
          </div>
        ),
    },
    {
      id: 'members',
      header: t('common.members'),
      cell: (role) => (
        <span className="text-sm text-muted-foreground">
          {t('team.rolesSection.memberCount', { count: role.member_count })}
        </span>
      ),
    },
    {
      id: 'actions',
      header: '',
      className: 'w-24',
      mobileActions: true,
      cell: (role) => (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => openEdit(role)}
            aria-label={
              canManage && !role.is_system ? t('team.rolesSection.editRole') : t('team.rolesSection.viewRole')
            }
          >
            {canManage && !role.is_system ? (
              <Pencil className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Eye className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
          {canManage && !role.is_system && (
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
                    {t('team.rolesSection.deleteConfirm', { name: roleDisplayName(role, t) })}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => handleDelete(role)}
                    disabled={deleteMut.isPending}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    {t('common.delete')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      ),
    },
  ];

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
        {canManage && (
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('team.rolesSection.addRole')}
          </Button>
        )}
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
        <Card>
          <CardContent className="p-0">
            <ResponsiveDataTable
              columns={columns}
              rows={companyRoles}
              getRowId={(role) => role.id}
            />
          </CardContent>
        </Card>
      )}

      <RoleEditorSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        editingRole={editingRole}
        readOnly={!canManage || (editingRole?.is_system ?? false)}
      />
    </div>
  );
}
