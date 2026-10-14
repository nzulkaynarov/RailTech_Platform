/**
 * Роль бэк-офиса: создание, правка своей роли и просмотр (системная роль или нет `team.manage`) —
 * каталог прав по разделам (M1-ERP-05).
 */
import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2, Lock } from 'lucide-react';

import { useCreateCompanyRole, useUpdateCompanyRole, usePermissionCatalog } from '@/hooks/useAccounts';
import type { CompanyRole } from '@/api/accountsApi';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from '@/components/ui/sheet';

import { permLabelKey, resolveRoleError, roleDisplayName } from './roleErrors';

interface RoleSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editingRole: CompanyRole | null;
  /** Только просмотр: системная роль или у сотрудника нет `team.manage`. */
  readOnly?: boolean;
}

export function RoleEditorSheet({ open, onOpenChange, editingRole, readOnly = false }: RoleSheetProps) {
  const { t } = useTranslation();
  const { data: permissionGroups = [] } = usePermissionCatalog();
  const createMut = useCreateCompanyRole();
  const updateMut = useUpdateCompanyRole();

  const isEdit = editingRole !== null;
  const isSystemRole = editingRole?.is_system ?? false;

  const [name, setName] = useState('');
  const [selectedPerms, setSelectedPerms] = useState<Set<string>>(new Set());

  // Пересобрать форму на открытии/смене роли — паттерн React «adjusting state when props
  // change» вместо побочного эффекта в `useMemo` (react-hooks/set-state-in-render).
  const [syncedFor, setSyncedFor] = useState<{ open: boolean; role: CompanyRole | null }>({
    open,
    role: editingRole,
  });
  if (syncedFor.open !== open || syncedFor.role !== editingRole) {
    setSyncedFor({ open, role: editingRole });
    if (open) {
      setName(editingRole ? roleDisplayName(editingRole, t) : '');
      setSelectedPerms(new Set(editingRole?.permissions ?? []));
    }
  }

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
            {readOnly
              ? t('team.rolesSection.viewRole')
              : isEdit
                ? t('team.rolesSection.editRole')
                : t('team.rolesSection.addRole')}
          </SheetTitle>
        </SheetHeader>

        {isSystemRole && (
          <div className="mx-4 mb-4 flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
            <Lock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">{t('team.rolesSection.systemRoleReadonly')}</p>
          </div>
        )}
        <form id="role-editor-form" onSubmit={handleSubmit} className="px-4 space-y-6">
          <fieldset disabled={readOnly} className="space-y-6">
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
                                disabled={readOnly}
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
          </fieldset>
        </form>

        {readOnly ? (
          <SheetFooter className="gap-2 pt-4">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.close')}
            </Button>
          </SheetFooter>
        ) : (
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
