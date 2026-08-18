import { FormEvent, useState } from 'react';
import { operatorPermLabelKey } from '@/lib/operatorPermLabels';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ShieldCheck, Loader2, Plus, Pencil, Trash2, Lock } from 'lucide-react';
import type { TFunction } from 'i18next';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
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

import {
  useOperatorRoles,
  useOperatorPermissionCatalog,
  useCreateOperatorRole,
  useUpdateOperatorRole,
  useDeleteOperatorRole,
} from '@/hooks/useAdmin';
import type { OperatorRole } from '@/api/adminApi';
import { useOperatorCan } from '@/hooks/useViewerMode';
import { PageShell, ErrorState } from './shared/PageShell';

// ─── Error helpers ──────────────────────────────────────────────────────────

interface BackendErrorShape {
  response?: { data?: { error?: string; detail?: string } };
}

/** Backend service error codes → i18n message keys (see accounts/views/operators.py). */
const OPERATOR_ROLE_ERROR_KEYS: Record<string, string> = {
  ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS:
    'operatorRoles.errors.ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS',
  SYSTEM_OPERATOR_ROLE_IMMUTABLE: 'operatorRoles.errors.SYSTEM_OPERATOR_ROLE_IMMUTABLE',
  ROLE_HAS_OPERATORS_REASSIGN_FIRST: 'operatorRoles.errors.ROLE_HAS_OPERATORS_REASSIGN_FIRST',
  CANNOT_DEMOTE_LAST_OPERATOR: 'operatorRoles.errors.CANNOT_DEMOTE_LAST_OPERATOR',
  NOT_A_PLATFORM_OPERATOR: 'operatorRoles.errors.NOT_A_PLATFORM_OPERATOR',
  ROLE_NAME_TAKEN: 'operatorRoles.errors.ROLE_NAME_TAKEN',
};


/** Resolve a thrown axios error to a localized, human-readable message. */
function resolveOperatorRoleError(
  err: unknown,
  translate: TFunction,
  fallbackKey: string,
): string {
  const data = (err as BackendErrorShape)?.response?.data;
  const code = data?.detail ?? data?.error;
  if (code && OPERATOR_ROLE_ERROR_KEYS[code]) {
    return translate(OPERATOR_ROLE_ERROR_KEYS[code]);
  }
  if (data?.detail) return data.detail;
  return translate(fallbackKey);
}

// ─── Role Editor Sheet ──────────────────────────────────────────────────────

interface RoleSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editingRole: OperatorRole | null;
}

function OperatorRoleEditorSheet({ open, onOpenChange, editingRole }: RoleSheetProps) {
  const { t } = useTranslation();
  const { data: permissionGroups = [] } = useOperatorPermissionCatalog();
  const createMut = useCreateOperatorRole();
  const updateMut = useUpdateOperatorRole();

  const isEdit = editingRole !== null;
  const isSystemRole = editingRole?.is_system ?? false;

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedPerms, setSelectedPerms] = useState<Set<string>>(new Set());

  // Пересобрать форму, когда лист открылся или сменилась роль. Раньше синхронизацию делал
  // `useMemo` — побочный эффект в мемо, который React вправе пересчитать в любой момент
  // (react-hooks/set-state-in-render). Здесь официальный паттерн React «adjusting state when
  // props change»: сравнение с предыдущими значениями прямо в рендере, без промежуточного кадра.
  const [syncedFor, setSyncedFor] = useState<{ open: boolean; role: OperatorRole | null }>({
    open,
    role: editingRole,
  });
  if (syncedFor.open !== open || syncedFor.role !== editingRole) {
    setSyncedFor({ open, role: editingRole });
    if (open) {
      setName(editingRole?.name ?? '');
      setDescription(editingRole?.description ?? '');
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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const permissions = Array.from(selectedPerms);
    try {
      if (isEdit && editingRole) {
        await updateMut.mutateAsync({ id: editingRole.id, data: { name, permissions, description } });
        toast.success(t('operatorRoles.updateSuccess'));
      } else {
        await createMut.mutateAsync({ name, permissions, description });
        toast.success(t('operatorRoles.createSuccess'));
      }
      onOpenChange(false);
    } catch (err) {
      toast.error(resolveOperatorRoleError(err, t, 'common.error'));
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader className="pb-4">
          <SheetTitle>
            {isEdit ? t('operatorRoles.editRole') : t('operatorRoles.addRole')}
          </SheetTitle>
        </SheetHeader>

        {isSystemRole ? (
          <div className="mx-4 flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
            <Lock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">{t('operatorRoles.systemRoleReadonly')}</p>
          </div>
        ) : (
          <form id="operator-role-editor-form" onSubmit={handleSubmit} className="space-y-6 px-4">
            <div className="space-y-1.5">
              <Label htmlFor="operator-role-name">{t('operatorRoles.name')}</Label>
              <Input
                id="operator-role-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('operatorRoles.namePlaceholder')}
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="operator-role-description">{t('operatorRoles.descriptionField')}</Label>
              <Textarea
                id="operator-role-description"
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder={t('operatorRoles.descriptionPlaceholder')}
              />
            </div>

            <div className="space-y-3">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">
                  {t('operatorRoles.permissions')}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t('operatorRoles.permissionsHint')}
                </p>
              </div>
              {permissionGroups.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
              ) : (
                <div className="space-y-5">
                  {permissionGroups.map((group) => {
                    const groupLabel = t(`operatorPermissions.${group.key}`, {
                      defaultValue: group.label,
                    });
                    return (
                      <div key={group.key} className="space-y-2">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          {groupLabel}
                        </p>
                        <div className="grid grid-cols-1 gap-2">
                          {group.permissions.map((perm) => (
                            <label
                              key={perm.code}
                              htmlFor={`operator-perm-${perm.code}`}
                              className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-border px-3 py-2 transition-colors hover:bg-muted/40"
                            >
                              <Checkbox
                                id={`operator-perm-${perm.code}`}
                                checked={selectedPerms.has(perm.code)}
                                onCheckedChange={() => togglePerm(perm.code)}
                              />
                              <span className="text-sm text-foreground">
                                {t(operatorPermLabelKey(perm.code), { defaultValue: perm.label })}
                              </span>
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
              form="operator-role-editor-form"
              disabled={isPending || !name.trim()}
            >
              {isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {t('operatorRoles.saveRole')}
            </Button>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────

export function AdminOperatorRolesPage() {
  const { t } = useTranslation();
  // Client-side capability gate (audit F3-UX): hide mutation controls from an operator
  // who lacks `operators.manage` instead of showing controls that only 403 on save.
  const canManage = useOperatorCan('operators.manage');
  const { data: operatorRoles = [], isLoading, isError, refetch } = useOperatorRoles();
  const deleteMut = useDeleteOperatorRole();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<OperatorRole | null>(null);

  function openCreate() {
    setEditingRole(null);
    setSheetOpen(true);
  }

  function openEdit(role: OperatorRole) {
    setEditingRole(role);
    setSheetOpen(true);
  }

  async function handleDelete(role: OperatorRole) {
    try {
      await deleteMut.mutateAsync(role.id);
      toast.success(t('operatorRoles.deleteSuccess'));
    } catch (err) {
      toast.error(resolveOperatorRoleError(err, t, 'common.error'));
    }
  }

  const stats = [
    { label: t('operatorRoles.stats.total'), value: String(operatorRoles.length) },
    {
      label: t('operatorRoles.stats.system'),
      value: String(operatorRoles.filter((role) => role.is_system).length),
    },
  ];

  return (
    <PageShell
      title={t('operatorRoles.title')}
      description={t('operatorRoles.description')}
      icon={<ShieldCheck className="h-5 w-5" />}
      stats={stats}
    >
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
        <div className="space-y-4">
          {canManage && (
            <div className="flex items-center justify-end">
              <Button size="sm" onClick={openCreate}>
                <Plus className="h-4 w-4" aria-hidden="true" />
                {t('operatorRoles.addRole')}
              </Button>
            </div>
          )}

          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
            </div>
          ) : operatorRoles.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t('operatorRoles.noRoles')}
            </p>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-border">
              <Table>
                <TableHeader>
                  <TableRow className="border-b border-border bg-muted/50 text-xs">
                    <TableHead className="p-4">{t('operatorRoles.name')}</TableHead>
                    <TableHead className="p-4">{t('operatorRoles.code')}</TableHead>
                    <TableHead className="p-4">{t('operatorRoles.permissions')}</TableHead>
                    <TableHead className="p-4">{t('operatorRoles.operatorCount')}</TableHead>
                    <TableHead className="w-24 p-4" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {operatorRoles.map((role) => (
                    <TableRow key={role.id} className="transition-colors hover:bg-muted/40">
                      <TableCell className="p-4">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-foreground">{role.name}</span>
                          {role.is_system && (
                            <Badge variant="secondary" className="gap-1 text-xs">
                              <Lock className="h-3 w-3" aria-hidden="true" />
                              {t('operatorRoles.systemRole')}
                            </Badge>
                          )}
                        </div>
                        {role.description && (
                          <p className="mt-0.5 text-xs text-muted-foreground">{role.description}</p>
                        )}
                      </TableCell>
                      <TableCell className="p-4">
                        <span className="font-mono text-xs text-muted-foreground">{role.code}</span>
                      </TableCell>
                      <TableCell className="p-4">
                        <Badge variant="outline" className="text-xs font-normal tabular-nums">
                          {role.permissions.length}
                        </Badge>
                      </TableCell>
                      <TableCell className="p-4">
                        <span className="text-sm tabular-nums text-muted-foreground">
                          {role.operator_count}
                        </span>
                      </TableCell>
                      <TableCell className="p-4">
                        <div className="flex items-center gap-1">
                          {canManage && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => openEdit(role)}
                            aria-label={t('operatorRoles.editRole')}
                          >
                            <Pencil className="h-4 w-4" aria-hidden="true" />
                          </Button>
                          )}
                          {canManage && !role.is_system && (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-destructive hover:text-destructive"
                                  aria-label={t('operatorRoles.deleteRole')}
                                  disabled={deleteMut.isPending}
                                >
                                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>{t('operatorRoles.deleteRole')}</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    {t('operatorRoles.deleteConfirm', { name: role.name })}
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
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}

      <OperatorRoleEditorSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        editingRole={editingRole}
      />
    </PageShell>
  );
}

export default AdminOperatorRolesPage;
