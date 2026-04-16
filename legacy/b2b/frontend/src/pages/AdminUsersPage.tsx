import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Shield, Search, Eye, Check, Pause,
  Mail, Phone, Building2, Calendar, User,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet';
import { useUsers, useToggleUserActive } from '@/hooks/useAccounts';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { User as UserType } from '@/api/accountsApi';

/* ─── Detail Sheet ─────────────────────────────────────────────────── */

function DetailSheet({
  user,
  open,
  onOpenChange,
  onToggleActive,
}: {
  user: UserType | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleActive: (user: UserType) => void;
}) {
  const { t } = useTranslation();
  if (!user) return null;

  const infoRows = [
    { icon: Mail, value: user.email },
    ...(user.phone ? [{ icon: Phone, value: user.phone }] : []),
    ...(user.company?.name ? [{ icon: Building2, value: user.company.name }] : []),
    { icon: Calendar, value: user.date_joined ? new Date(user.date_joined).toLocaleDateString() : t('pages.adminUsers.detail.noData') },
  ];

  const roleName = user.role_data?.name;

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
          {/* Contact Info */}
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

          {/* Role & Status */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('pages.adminUsers.detail.access')}</h3>

            {/* Role */}
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('pages.adminUsers.table.role')}</span>
              {roleName ? (
                <Badge variant={user.role_data?.is_staff_level ? 'default' : 'secondary'}>
                  {roleName}
                </Badge>
              ) : (
                <span className="text-sm text-muted-foreground">{t('pages.adminUsers.detail.noRole')}</span>
              )}
            </div>

            {/* Status with toggle */}
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{t('pages.adminUsers.table.status')}</span>
              <div className="flex items-center gap-3">
                <span className={`text-sm font-medium ${user.is_active ? 'text-success' : 'text-destructive'}`}>
                  {user.is_active ? t('pages.adminUsers.statusLabel.active') : t('pages.adminUsers.statusLabel.inactive')}
                </span>
                <Switch
                  checked={user.is_active}
                  onCheckedChange={() => onToggleActive(user)}
                />
              </div>
            </div>

            {/* Last login */}
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
      </SheetContent>
    </Sheet>
  );
}

/* ─── Main Page ────────────────────────────────────────────────────── */

export function AdminUsersPage() {
  const { t } = useTranslation();
  const { data: users, isLoading } = useUsers();
  const toggleActiveMutation = useToggleUserActive();

  const [search, setSearch] = useState('');
  const [detailTarget, setDetailTarget] = useState<UserType | null>(null);

  const selectedUser = useMemo(() => {
    if (!detailTarget || !users) return null;
    return users.find((u) => u.id === detailTarget.id) ?? detailTarget;
  }, [users, detailTarget]);

  const filtered = useMemo(() => {
    if (!users) return [];
    if (!search.trim()) return users;
    const q = search.toLowerCase();
    return users.filter((u) =>
      u.email.toLowerCase().includes(q) ||
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) ||
      (u.phone ?? '').includes(q)
    );
  }, [users, search]);

  const stats = [
    { label: t('pages.adminUsers.stats.total'), value: String(users?.length ?? '—') },
    { label: t('pages.adminUsers.stats.active'), value: String(users?.filter((u) => u.is_active).length ?? '—') },
    { label: t('pages.adminUsers.stats.staff'), value: String(users?.filter((u) => u.role_data?.is_staff_level).length ?? '—') },
    { label: t('pages.adminUsers.stats.inactive'), value: String(users?.filter((u) => !u.is_active).length ?? '—') },
  ];

  const handleToggleActive = async (user: UserType) => {
    try {
      await toggleActiveMutation.mutateAsync(user.id);
      toast.success(
        user.is_active
          ? t('pages.adminUsers.deactivated', { name: user.email })
          : t('pages.adminUsers.activated', { name: user.email })
      );
    } catch {
      toast.error(t('common.error'));
    }
  };

  return (
    <PageShell
      title={t('pages.adminUsers.title')}
      description={t('pages.adminUsers.description')}
      icon={<Shield className="h-5 w-5" />}
      stats={stats}
    >
      {/* Search */}
      <div className="relative flex-1 max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder={t('pages.adminUsers.searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={5} /> : !filtered.length ? (
            <EmptyState icon={<Shield className="h-5 w-5" />} message={t('pages.common.noData')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('pages.adminUsers.table.name')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.email')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.role')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.status')}</TableHead>
                  <TableHead>{t('pages.adminUsers.table.lastLogin')}</TableHead>
                  <TableHead className="text-center">{t('pages.adminUsers.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((user) => (
                  <TableRow
                    key={user.id}
                    className="cursor-pointer"
                    onClick={() => setDetailTarget(user)}
                  >
                    <TableCell>
                      <span className="font-medium">{user.first_name} {user.last_name}</span>
                    </TableCell>
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
                    <TableCell className="text-center">
                      <div className="flex justify-center" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDetailTarget(user)}
                          title={t('pages.adminUsers.detail.info')}
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <DetailSheet
        user={selectedUser}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
        onToggleActive={handleToggleActive}
      />
    </PageShell>
  );
}

export default AdminUsersPage;
