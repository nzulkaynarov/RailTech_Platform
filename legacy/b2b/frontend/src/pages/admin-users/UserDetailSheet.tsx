import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Check, Pause, Mail, Phone, Calendar, User, Trash2, AlertTriangle,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { formatDate, formatDateTime } from '@/lib/formatLocale';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { useDraftState } from '@/hooks/useDraftState';
import { DetailKPIGrid } from '@/components/Admin/DetailKPIGrid';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter,
} from '@/components/ui/sheet';
import {
  useToggleUserActive, useSystemRoles, useChangeUserRole, useUpdateUser,
  useUploadUserAvatar, useDeleteUserAvatar,
} from '@/hooks/useAccounts';
import { useOperatorRoles, useAssignOperatorRole } from '@/hooks/useAdmin';
import { useOperatorCan } from '@/hooks/useViewerMode';
import { systemRoleLabelKey } from '@/lib/codes';
import type { User as UserType } from '@/api/accountsApi';
import { ImageUpload } from '@/components/Shared/ImageUpload';
import { MembershipsPanel } from './MembershipsPanel';
import { NO_OPERATOR_ROLE, type Draft } from './types';

export function UserDetailSheet({
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
  const { data: operatorRoles } = useOperatorRoles();
  const assignOperatorMut = useAssignOperatorRole();
  // Hide the operator-role assignment control from an operator without `operators.manage`
  // (audit F3-UX) — it otherwise only 403s on save.
  const canManageOperators = useOperatorCan('operators.manage');

  // Черновик и роль пересобираются при смене пользователя прямо в рендере — без кадра,
  // на котором в шторке ещё видны поля предыдущего сотрудника.
  const [draft, setDraft] = useDraftState<typeof user, Draft>(user, (source) => (source ? { ...source } : {}));
  const [roleCode, setRoleCode] = useDraftState(user, (source) => source?.role_code ?? source?.role_data?.code ?? '');
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);

  if (!user) return null;

  const busy = toggleMut.isPending || changeRoleMut.isPending || updateMut.isPending;
  const memberships = user.memberships ?? [];
  const hasMemberships = memberships.length > 0;
  // ADMIN можно назначить только юзеру без memberships (см. services.change_user_role).
  const adminDisabledReason = hasMemberships ? t('pages.adminUsers.errors.ADMIN_ROLE_REQUIRES_NO_MEMBERSHIPS') : '';

  const infoRows = [
    { icon: Mail, value: user.email },
    ...(user.phone ? [{ icon: Phone, value: user.phone }] : []),
    { icon: Calendar, value: user.date_joined ? formatDate(user.date_joined) : '—' },
  ];

  const runToggleActive = async () => {
    try {
      await toggleMut.mutateAsync(user.id);
      toast.success(
        user.is_active
          ? t('pages.adminUsers.deactivated', { name: user.email })
          : t('pages.adminUsers.activated', { name: user.email })
      );
    } catch (e) {
      const detail = (e as { response?: { data?: { error?: string; detail?: string } } })?.response?.data;
      const code = detail?.error || detail?.detail;
      toast.error(code ? t(`pages.adminUsers.errors.${code}`, code) : t('common.error'));
    }
  };

  // Deactivation is destructive (revokes the user's access) — gate it behind a
  // confirm. Re-activation is benign and fires immediately.
  const handleToggleActive = (next: boolean) => {
    if (!next && user.is_active) {
      setConfirmDeactivate(true);
      return;
    }
    void runToggleActive();
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

  // Operator sub-role (ADR-0004 G1) — only meaningful for platform operators.
  // The "none" sentinel maps to a null role_id (clears the assignment).
  const handleAssignOperatorRole = async (value: string) => {
    const roleId = value === NO_OPERATOR_ROLE ? null : Number(value);
    try {
      await assignOperatorMut.mutateAsync({ userId: user.id, roleId });
      // Снятие суб-роли — НЕ назначение: без неё оператор проходит любую проверку права
      // (`accounts/services/permissions.py`: `op_role is None → True`). Прежний текст
      // «Роль оператора назначена» печатался и в этом случае, то есть расширение прав до
      // полного доступа сообщалось словами об ограничении.
      toast.success(roleId === null ? t('operatorRoles.limitsRemoved') : t('operatorRoles.assignSuccess'));
    } catch (e) {
      const data = (e as { response?: { data?: { error?: string; detail?: string } } })?.response?.data;
      const code = data?.detail ?? data?.error;
      toast.error(
        code
          ? t(`operatorRoles.errors.${code}`, { defaultValue: data?.detail ?? t('common.error') })
          : data?.detail ?? t('common.error'),
      );
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
                {hasMemberships && <Badge variant="outline" className="ml-1.5 text-xs">{memberships.length}</Badge>}
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
                    value: user.role_data?.code ? t(systemRoleLabelKey(user.role_data.code)) : '—',
                  },
                  {
                    label: t('pages.adminUsers.tabs.memberships'),
                    value: String(memberships.length),
                  },
                  {
                    label: t('pages.adminUsers.table.lastLogin'),
                    value: user.last_login
                      ? formatDate(user.last_login)
                      : '—',
                    hint: user.date_joined
                      ? t('pages.adminUsers.joinedHint', {
                          date: formatDate(user.date_joined),
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
                  <span className="tabular-nums">{formatDateTime(user.last_login)}</span>
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
                          {t(systemRoleLabelKey(r.code))}
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

              {/* Operator sub-role — only for platform operators (ADR-0004 G1), and only
                  editable by an operator holding operators.manage (audit F3-UX). */}
              {user.is_platform_admin && canManageOperators && (
                <div className="space-y-2 rounded-lg border p-3">
                  <Label>{t('operatorRoles.assignRole')}</Label>
                  <Select
                    value={user.operator_role_data?.id ? String(user.operator_role_data.id) : NO_OPERATOR_ROLE}
                    onValueChange={handleAssignOperatorRole}
                    disabled={assignOperatorMut.isPending}
                  >
                    <SelectTrigger aria-label={t('operatorRoles.assignRole')}>
                      <SelectValue placeholder={t('operatorRoles.noOperatorRole')} />
                    </SelectTrigger>
                    <SelectContent>
                      {/* Пункт называется тем, чем является: он не «оставляет без роли», а
                          СНИМАЕТ ограничения. Раньше подпись обещала обратное. */}
                      <SelectItem value={NO_OPERATOR_ROLE}>{t('operatorRoles.fullAccessNoLimits')}</SelectItem>
                      {(operatorRoles ?? []).map((operatorRole) => (
                        <SelectItem key={operatorRole.id} value={String(operatorRole.id)}>
                          {operatorRole.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">{t('operatorRoles.assignHint')}</p>
                </div>
              )}
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

        <ConfirmActionDialog
          open={confirmDeactivate}
          onOpenChange={setConfirmDeactivate}
          title={t('pages.adminUsers.confirmDeactivateTitle')}
          description={t('pages.adminUsers.confirmDeactivateDesc', { name: user.email })}
          confirmLabel={t('pages.adminUsers.deactivateConfirm')}
          variant="destructive"
          onConfirm={async () => { await runToggleActive(); }}
        />
      </SheetContent>
    </Sheet>
  );
}
